"""Layer 6+7 — 청산 규칙 & 보유 종목 건강검진.

매일 보유 종목마다 훼손 신호를 점검하고 HOLD/TRIM/SELL 을 판정한다.
교체(ROTATE)는 recommender 에서 후보와 비교해 결정.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from tradroom.config import STRATEGY
from tradroom.data.base import MarketData
from tradroom.features.engine import FactorPanel


@dataclass
class Position:
    """사용자 보유 종목."""

    ticker: str
    shares: int
    avg_price: float
    high_since_entry: float | None = None   # 트레일링용 진입 후 고점


@dataclass
class HealthCheck:
    ticker: str
    name: str
    action: str               # HOLD | TRIM | SELL
    score: float
    triggers: list[str] = field(default_factory=list)
    price: float = 0.0
    pnl_pct: float = 0.0


def _exit_triggers(
    md: MarketData, fp: FactorPanel, pos: Position, date: pd.Timestamp, score: float
) -> list[str]:
    e = STRATEGY.exit
    triggers = []
    close = md.close[pos.ticker]
    price = close.loc[date]

    # 진입 후 고점(없으면 보유구간 max 추정)
    hi = pos.high_since_entry
    if hi is None:
        hist = close.loc[close.index <= date].tail(120)
        hi = float(hist.max())
    hi = max(hi, price)

    # 1) 트레일링 스탑: 고점 대비 -X%
    if price <= hi * (1 - e.trailing_stop_pct):
        triggers.append(f"트레일링 손절(고점 대비 {(price/hi-1)*100:.0f}%)")

    # 2) 추세 훼손: 종가 < MA60
    ma = fp.raw["ma60"][pos.ticker].loc[date]
    if pd.notna(ma) and price < ma:
        triggers.append("추세훼손(MA60 하향이탈)")

    # 3) 상대강도 악화: RS 랭크 하위
    rs = fp.raw["rs_market_pct"][pos.ticker].loc[date]
    if pd.notna(rs) and rs < e.rs_exit_rank:
        triggers.append(f"상대강도 악화(RS {rs*100:.0f}%ile)")

    # 4) 수급 이탈: 최근 20일 순매수 음전환
    flow20 = md.net_flow[pos.ticker].loc[md.net_flow.index <= date].tail(20).sum()
    if flow20 < 0:
        triggers.append("수급 이탈(외/기관 순매도)")

    return triggers


def evaluate_holding(
    md: MarketData, fp: FactorPanel, pos: Position, date: pd.Timestamp
) -> HealthCheck:
    from tradroom.signals.scoring import composite_score

    score = float(composite_score(fp, date).get(pos.ticker, float("nan")))
    triggers = _exit_triggers(md, fp, pos, date, score)
    price = float(md.close[pos.ticker].loc[date])
    pnl = (price / pos.avg_price - 1) if pos.avg_price else 0.0

    # 의사결정 매트릭스
    hard = [t for t in triggers if "손절" in t or "추세훼손" in t]
    if hard:
        action = "SELL"
    elif len(triggers) >= 1:
        action = "TRIM"     # 일부 약화 → 리스크 절반
    else:
        action = "HOLD"

    return HealthCheck(
        ticker=pos.ticker,
        name=str(md.meta.loc[pos.ticker, "name"]) if pos.ticker in md.meta.index else pos.ticker,
        action=action,
        score=round(score, 1) if score == score else 0.0,
        triggers=triggers,
        price=round(price, 2),
        pnl_pct=round(pnl * 100, 2),
    )
