"""Layer 3 — 종목 선정 (하드 게이트 → 멀티팩터 종합점수).

(A) 게이트: 하나라도 실패하면 후보 탈락.
(B) 점수(0~100): 가중 백분위 합산.  게이트 통과 종목만 랭킹.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from tradroom.config import STRATEGY
from tradroom.data.base import MarketData
from tradroom.features.engine import FactorPanel
from tradroom.signals.sector import leading_sectors


def hard_gates(
    md: MarketData, fp: FactorPanel, date: pd.Timestamp, active_sectors: list[str]
) -> pd.Series:
    """종목별 게이트 통과 여부(bool Series, index=ticker)."""
    g = STRATEGY.gate
    close = md.close.loc[date]
    tickers = md.close.columns

    # 3) 유동성: 20일 평균 거래대금 >= 기준
    turnover = fp.raw["avg_turnover"].loc[date]
    gate_liq = turnover >= g.min_turnover_krw

    # 4) 추세 정상: 종가 > MA120 & 정배열점수 >= 3
    ma120 = fp.raw["ma120"].loc[date]
    align = fp.raw["ma_alignment"].loc[date]
    gate_trend = (close > ma120) & (align >= g.min_ma_alignment)

    # 2) 섹터: 주도 섹터 소속
    sector_ok = md.meta["sector"].isin(active_sectors).reindex(tickers).fillna(False)

    # 5) 지뢰 회피: 관리/거래정지/자본잠식 아님
    meta = md.meta.reindex(tickers)
    gate_safe = ~(meta["is_managed"] | meta["is_halted"] | meta["is_capital_impaired"])

    gates = (
        gate_liq.reindex(tickers).fillna(False)
        & gate_trend.reindex(tickers).fillna(False)
        & sector_ok.values
        & gate_safe.values
    )
    return pd.Series(gates, index=tickers)


def composite_score(fp: FactorPanel, date: pd.Timestamp) -> pd.Series:
    """종합점수 0~100 (게이트 무관, 전 종목)."""
    w = STRATEGY.weights
    tbl = fp.as_of(date)
    score = (
        w.trend * tbl["trend"]
        + w.relative_strength * tbl["relative_strength"]
        + w.quality * tbl["quality"]
        + w.supply * tbl["supply"]
        + w.valuation * tbl["valuation_cheapness"]
    ) * 100.0
    return score


def score_universe(
    md: MarketData, fp: FactorPanel, date: pd.Timestamp, regime_allows: bool = True
) -> pd.DataFrame:
    """게이트 + 점수 → 정렬된 후보 테이블.

    반환 컬럼: name, sector, score, passed_gate, 각 팩터 점수.
    regime_allows=False(Risk-Off) 면 passed_gate 전부 False(신규 후보 0).
    """
    active = leading_sectors(md, date)
    gates = hard_gates(md, fp, date, active)
    if not regime_allows:
        gates[:] = False

    score = composite_score(fp, date)
    tbl = fp.as_of(date)
    out = pd.DataFrame(
        {
            "name": md.meta["name"].reindex(score.index),
            "sector": md.meta["sector"].reindex(score.index),
            "score": score.round(1),
            "passed_gate": gates.reindex(score.index).fillna(False),
            "trend": (tbl["trend"] * 100).round(0),
            "relative_strength": (tbl["relative_strength"] * 100).round(0),
            "quality": (tbl["quality"] * 100).round(0),
            "supply": (tbl["supply"] * 100).round(0),
            "valuation": (tbl["valuation_cheapness"] * 100).round(0),
        }
    )
    out = out.replace([np.inf, -np.inf], np.nan)
    # 게이트 통과 우선, 그 안에서 점수 내림차순
    return out.sort_values(["passed_gate", "score"], ascending=[False, False])
