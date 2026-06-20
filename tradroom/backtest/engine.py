"""백테스트 엔진 — 전체 전략을 시간축으로 시뮬레이션.

흐름(매 거래일):
  - 레짐 → 허용 총노출 결정
  - (리밸런스 주기마다) 게이트+점수+타이밍으로 목표 보유 산출, 사이징
  - 매일 청산 규칙(손절/추세훼손/트레일링) 점검
  - 한국 규칙: 매도 거래세, 슬리피지, 유동성 한도, look-ahead 방지

체결 가정은 *다음 날 시가*(신호는 당일 종가 기준) — look-ahead 회피.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from tradroom.config import STRATEGY
from tradroom.data.base import MarketData
from tradroom.features.engine import FactorPanel, build_factor_panel
from tradroom.portfolio.sizing import position_size
from tradroom.signals.regime import regime_timeseries
from tradroom.signals.scoring import hard_gates, composite_score
from tradroom.signals.sector import leading_sectors
from tradroom.signals.timing import entry_timing


@dataclass
class _Holding:
    shares: int
    entry_price: float
    entry_date: pd.Timestamp
    stop_price: float
    high: float


@dataclass
class BacktestResult:
    equity: pd.Series
    trades: pd.DataFrame
    regime: pd.DataFrame
    exposure: pd.Series
    metrics: dict = field(default_factory=dict)


def run_backtest(
    md: MarketData,
    start: str | None = None,
    end: str | None = None,
    initial_equity: float = 1e8,
    rebalance_freq: int = 5,      # 거래일(주간 리밸런스)
    top_k: int | None = None,
    fp: FactorPanel | None = None,
    warmup: int = 252,            # 지표 안정화 구간 건너뛰기
) -> BacktestResult:
    from tradroom.backtest.metrics import performance_metrics

    fp = fp or build_factor_panel(md)
    regime_df = regime_timeseries(md)
    top_k = top_k or STRATEGY.risk.target_positions
    cost = STRATEGY.cost

    dates = md.dates
    lo = max(warmup, 0)
    if start:
        lo = max(lo, dates.searchsorted(pd.Timestamp(start)))
    hi = len(dates)
    if end:
        hi = min(hi, dates.searchsorted(pd.Timestamp(end)) + 1)
    sim_dates = dates[lo:hi]

    cash = initial_equity
    holdings: dict[str, _Holding] = {}
    equity_curve: dict[pd.Timestamp, float] = {}
    trades: list[dict] = []

    def price_on(tkr, d, field="close"):
        return float(getattr(md, field)[tkr].loc[d])

    for i, today in enumerate(sim_dates):
        # ---- 일일 마크투마켓 + 트레일링/청산 점검 ----
        for tkr, h in list(holdings.items()):
            px = price_on(tkr, today)
            h.high = max(h.high, px)
            sell, why = _check_exit(md, fp, tkr, h, today)
            if sell:
                cash += _sell(trades, tkr, h, today, _next_open(md, sim_dates, i, tkr), cost, why)
                del holdings[tkr]

        # ---- 리밸런스: 신규 후보 매수 ----
        regime_row = regime_df.loc[today]
        allow = regime_row["label"] != "Risk-Off"
        exposure = float(regime_row["exposure"])

        if i % rebalance_freq == 0 and allow:
            equity_now = cash + sum(
                h.shares * price_on(t, today) for t, h in holdings.items()
            )
            target = _target_buys(md, fp, today, top_k, set(holdings))
            # 노출 한도 내에서만 신규
            invested = sum(h.shares * price_on(t, today) for t, h in holdings.items())
            budget = max(0.0, equity_now * exposure - invested)
            for tkr in target:
                if tkr in holdings or budget <= 0:
                    continue
                atr = float(fp.raw["atr"][tkr].loc[today])
                px = price_on(tkr, today)
                if not np.isfinite(atr) or atr <= 0 or px <= 0:
                    continue
                plan = position_size(tkr, px, atr, equity_now, regime_exposure=exposure)
                value = min(plan.target_value, budget, _liquidity_cap(md, tkr, today))
                shares = int(value // px)
                if shares <= 0:
                    continue
                fill = _next_open(md, sim_dates, i, tkr) or px
                fill *= 1 + cost.slippage
                cost_buy = shares * fill * (1 + cost.commission)
                if cost_buy > cash:
                    shares = int(cash // (fill * (1 + cost.commission)))
                    cost_buy = shares * fill * (1 + cost.commission)
                if shares <= 0:
                    continue
                cash -= cost_buy
                budget -= shares * fill
                holdings[tkr] = _Holding(
                    shares=shares, entry_price=fill, entry_date=today,
                    stop_price=plan.stop_price, high=fill,
                )

        equity_curve[today] = cash + sum(
            h.shares * price_on(t, today) for t, h in holdings.items()
        )

    # 종료 시 청산
    last = sim_dates[-1]
    for tkr, h in list(holdings.items()):
        cash += _sell(trades, tkr, h, last, price_on(tkr, last), cost, "백테스트 종료")

    equity = pd.Series(equity_curve).sort_index()
    trades_df = pd.DataFrame(trades)
    metrics = performance_metrics(equity, trades_df)
    metrics["turnover"] = round(len(trades_df) / (len(equity) / 252 + 1e-9), 1) if len(equity) else 0
    return BacktestResult(
        equity=equity, trades=trades_df,
        regime=regime_df.loc[sim_dates], exposure=regime_df.loc[sim_dates, "exposure"],
        metrics=metrics,
    )


# --------------------------------------------------------------------- helpers
def _next_open(md: MarketData, sim_dates, i: int, tkr: str) -> float | None:
    """다음 거래일 시가(체결가).  마지막날이면 None → 당일 종가 사용."""
    if i + 1 >= len(sim_dates):
        return None
    nd = sim_dates[i + 1]
    try:
        o = float(md.open[tkr].loc[nd])
        return o if np.isfinite(o) and o > 0 else None
    except KeyError:
        return None


def _liquidity_cap(md: MarketData, tkr: str, date: pd.Timestamp) -> float:
    """유동성 한도: 20일 평균 거래대금의 10% 까지만 체결 가능 가정."""
    val = md.value[tkr].loc[md.value.index <= date].tail(20).mean()
    return float(val) * 0.10 if np.isfinite(val) else 0.0


def _target_buys(md, fp, date, top_k, held) -> list[str]:
    active = leading_sectors(md, date)
    gates = hard_gates(md, fp, date, active)
    score = composite_score(fp, date)
    ranked = score[gates].sort_values(ascending=False)
    out = []
    for tkr in ranked.index:
        if tkr in held:
            continue
        sig = entry_timing(md, fp, tkr, date)
        if sig.label == "BUY_NOW":
            out.append(tkr)
        if len(out) >= top_k:
            break
    return out


def _check_exit(md, fp, tkr, h: _Holding, date) -> tuple[bool, str]:
    e = STRATEGY.exit
    px = float(md.close[tkr].loc[date])
    if px <= h.stop_price:
        return True, "손절"
    if px <= h.high * (1 - e.trailing_stop_pct):
        return True, "트레일링 손절"
    ma = fp.raw["ma60"][tkr].loc[date]
    if pd.notna(ma) and px < ma:
        return True, "추세훼손(MA60)"
    rs = fp.raw["rs_market_pct"][tkr].loc[date]
    if pd.notna(rs) and rs < e.rs_exit_rank:
        return True, "상대강도 악화"
    return False, ""


def _sell(trades, tkr, h: _Holding, date, fill, cost, reason) -> float:
    fill = (fill or float("nan"))
    if not np.isfinite(fill) or fill <= 0:
        fill = h.entry_price
    fill *= 1 - cost.slippage
    proceeds = h.shares * fill * (1 - cost.commission - cost.sell_tax)
    cost_basis = h.shares * h.entry_price * (1 + cost.commission)
    pnl = proceeds - cost_basis
    trades.append(
        {
            "ticker": tkr, "entry_date": h.entry_date, "exit_date": date,
            "entry_price": round(h.entry_price, 2), "exit_price": round(fill, 2),
            "shares": h.shares, "pnl": round(pnl, 0),
            "return_pct": round((fill / h.entry_price - 1) * 100, 2),
            "reason": reason,
            "hold_days": (date - h.entry_date).days,
        }
    )
    return proceeds
