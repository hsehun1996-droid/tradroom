"""일일 추천 엔진 (블루프린트 4.7) — "지금 살만한 종목" + 보유 진단/교체.

내 보유를 입력하면 매일:
  1) 레짐 신호등
  2) 매수 후보 랭킹 (BUY_NOW / WATCH) + 사이징
  3) 보유 종목 건강검진 (HOLD/TRIM/SELL)
  4) 교체(ROTATE) 추천 — 마찰(임계치)로 잦은 교체 억제
을 산출한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from tradroom.config import STRATEGY
from tradroom.data.base import MarketData
from tradroom.features.engine import FactorPanel, build_factor_panel
from tradroom.portfolio.monitor import HealthCheck, Position, evaluate_holding
from tradroom.portfolio.sizing import PositionPlan, position_size
from tradroom.signals.regime import RegimeState, compute_regime
from tradroom.signals.scoring import score_universe
from tradroom.signals.timing import entry_timing


@dataclass
class BuyCandidate:
    ticker: str
    name: str
    sector: str
    score: float
    timing: str           # BUY_NOW | WATCH
    timing_reason: str
    factors: dict
    plan: PositionPlan | None = None


@dataclass
class RotateIdea:
    sell_ticker: str
    sell_name: str
    buy_ticker: str
    buy_name: str
    sell_score: float
    buy_score: float
    reason: str


@dataclass
class Recommendation:
    date: str
    regime: RegimeState
    buy_candidates: list[BuyCandidate] = field(default_factory=list)
    holdings: list[HealthCheck] = field(default_factory=list)
    rotations: list[RotateIdea] = field(default_factory=list)


def daily_recommendation(
    md: MarketData,
    holdings: list[Position] | None = None,
    total_equity: float = 1e8,
    date: pd.Timestamp | None = None,
    top_k: int = 15,
    fp: FactorPanel | None = None,
) -> Recommendation:
    fp = fp or build_factor_panel(md)
    date = pd.Timestamp(date) if date is not None else md.dates[-1]
    holdings = holdings or []

    # 1) 레짐
    regime = compute_regime(md, date)

    # 2) 매수 후보
    ranked = score_universe(md, fp, date, regime_allows=regime.allow_new_entry)
    passed = ranked[ranked["passed_gate"]].head(top_k)

    held_tickers = {h.ticker for h in holdings}
    # 섹터 현재 비중(교체/캡 계산용)
    sector_weight = _current_sector_weights(md, holdings, total_equity, date)

    candidates: list[BuyCandidate] = []
    for tkr, row in passed.iterrows():
        sig = entry_timing(md, fp, tkr, date)
        plan = None
        if sig.label == "BUY_NOW" and tkr not in held_tickers:
            atr = float(fp.raw["atr"][tkr].loc[date])
            price = float(md.close[tkr].loc[date])
            plan = position_size(
                tkr, price, atr, total_equity,
                regime_exposure=regime.exposure,
                current_sector_weight=sector_weight.get(row["sector"], 0.0),
            )
        candidates.append(
            BuyCandidate(
                ticker=tkr, name=str(row["name"]), sector=str(row["sector"]),
                score=float(row["score"]), timing=sig.label, timing_reason=sig.reason,
                factors={
                    "trend": row["trend"], "relative_strength": row["relative_strength"],
                    "quality": row["quality"], "supply": row["supply"],
                    "valuation": row["valuation"],
                },
                plan=plan,
            )
        )

    # 3) 보유 진단
    holding_checks = [evaluate_holding(md, fp, h, date) for h in holdings]

    # 4) 교체 추천
    rotations = _rotation_ideas(holding_checks, candidates, ranked)

    return Recommendation(
        date=str(date.date()),
        regime=regime,
        buy_candidates=candidates,
        holdings=holding_checks,
        rotations=rotations,
    )


def _current_sector_weights(md, holdings, total_equity, date) -> dict[str, float]:
    weights: dict[str, float] = {}
    if total_equity <= 0:
        return weights
    for h in holdings:
        if h.ticker not in md.close.columns:
            continue
        val = h.shares * float(md.close[h.ticker].loc[date])
        sec = str(md.meta.loc[h.ticker, "sector"]) if h.ticker in md.meta.index else "기타"
        weights[sec] = weights.get(sec, 0.0) + val / total_equity
    return weights


def _rotation_ideas(
    holding_checks: list[HealthCheck],
    candidates: list[BuyCandidate],
    ranked: pd.DataFrame,
) -> list[RotateIdea]:
    """교체 = 약화된 보유 종목 + 그보다 +임계치 이상 좋은 미보유 후보."""
    gap = STRATEGY.rotate.score_gap_threshold
    ideas: list[RotateIdea] = []
    held = {h.ticker for h in holding_checks}
    fresh = [c for c in candidates if c.ticker not in held and c.timing == "BUY_NOW"]
    fresh.sort(key=lambda c: c.score, reverse=True)

    # 약화 신호가 있는 보유(TRIM/SELL)만 교체 대상
    weak = [h for h in holding_checks if h.action in ("TRIM", "SELL")]
    weak.sort(key=lambda h: h.score)

    used = set()
    for h in weak:
        for c in fresh:
            if c.ticker in used:
                continue
            if c.score - h.score >= gap:
                ideas.append(
                    RotateIdea(
                        sell_ticker=h.ticker, sell_name=h.name,
                        buy_ticker=c.ticker, buy_name=c.name,
                        sell_score=h.score, buy_score=c.score,
                        reason=f"{h.name} 약화({', '.join(h.triggers) or h.action}) → "
                               f"{c.name} 점수 {h.score:.0f}→{c.score:.0f} (+{c.score-h.score:.0f})",
                    )
                )
                used.add(c.ticker)
                break
    return ideas
