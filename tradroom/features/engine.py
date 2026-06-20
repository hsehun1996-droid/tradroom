"""팩터 엔진 — 5대 팩터 그룹을 조립해 정규화된 패널을 만든다.

블루프린트 4.3 / 5장.  출력 FactorPanel 의 각 그룹 점수는 횡단면 백분위(0~1).
스코어링(signals/scoring.py)이 이 백분위를 가중합한다.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from tradroom.data.base import MarketData
from tradroom.features import technical as ta
from tradroom.features.normalize import cross_sectional_percentile


@dataclass
class FactorPanel:
    """정규화된 팩터 그룹 점수 (index=date, columns=ticker, 값 0~1)."""

    trend: pd.DataFrame
    relative_strength: pd.DataFrame
    quality: pd.DataFrame
    supply: pd.DataFrame
    valuation_cheapness: pd.DataFrame   # 1=쌈, 0=비쌈 (이미 역방향 처리)

    # 원자료(게이트/타이밍/사이징에서 재사용)
    raw: dict

    def as_of(self, date: pd.Timestamp) -> pd.DataFrame:
        """특정 날짜의 그룹별 점수 테이블(index=ticker)."""
        return pd.DataFrame(
            {
                "trend": self.trend.loc[date],
                "relative_strength": self.relative_strength.loc[date],
                "quality": self.quality.loc[date],
                "supply": self.supply.loc[date],
                "valuation_cheapness": self.valuation_cheapness.loc[date],
            }
        )


def _avg_percentile(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """여러 백분위 패널의 평균(결측 무시) 후 다시 백분위화."""
    stacked = pd.concat(frames)
    avg = stacked.groupby(level=0).mean()
    return cross_sectional_percentile(avg)


def build_factor_panel(md: MarketData) -> FactorPanel:
    close = md.close

    # ---------- 추세·모멘텀 ----------
    mom_12_1 = ta.momentum(close, lookback=231, skip=21)   # 12개월(252)에서 1개월 제외 ≈ 231
    mom_6 = ta.momentum(close, lookback=126)
    align = ta.ma_alignment_score(close)
    hi52 = ta.high_proximity_52w(close)
    adx14 = ta.adx(md, 14)
    trend = _avg_percentile(
        [
            cross_sectional_percentile(mom_12_1),
            cross_sectional_percentile(mom_6),
            cross_sectional_percentile(align),
            cross_sectional_percentile(hi52),
            cross_sectional_percentile(adx14),
        ]
    )

    # ---------- 상대강도 (vs 시장/섹터) ----------
    kospi = md.macro["kospi_close"]
    mkt_ret = (kospi / kospi.shift(126) - 1).reindex(close.index).ffill()
    stock_ret = close / close.shift(126) - 1
    rs_market = stock_ret.sub(mkt_ret, axis=0)
    # 섹터 대비
    sec_ret = md.sector_index / md.sector_index.shift(126) - 1
    sec_ret_per_ticker = pd.DataFrame(index=close.index, columns=close.columns, dtype=float)
    for tkr in close.columns:
        sec = md.meta.loc[tkr, "sector"]
        if sec in sec_ret.columns:
            sec_ret_per_ticker[tkr] = sec_ret[sec]
    rs_sector = stock_ret - sec_ret_per_ticker
    relative_strength = _avg_percentile(
        [cross_sectional_percentile(rs_market), cross_sectional_percentile(rs_sector)]
    )

    # ---------- 퀄리티·성장 ----------
    roe = md.fin("roe")
    opm = md.fin("op_margin")
    debt = md.fin("debt_ratio")
    eps_yoy = md.fin("eps_yoy")
    rev_yoy = md.fin("revenue_yoy")
    quality = _avg_percentile(
        [
            cross_sectional_percentile(roe),
            cross_sectional_percentile(opm),
            cross_sectional_percentile(-debt),       # 부채는 낮을수록 좋음
            cross_sectional_percentile(eps_yoy),
            cross_sectional_percentile(rev_yoy),
        ]
    )

    # ---------- 수급 (한국형 알파) ----------
    flow_20 = md.net_flow.rolling(20, min_periods=10).sum()
    # 시총 대용: 거래대금 평균 (시총 패널이 없을 때) — 비율화
    mcap_proxy = md.value.rolling(20, min_periods=10).mean().replace(0, np.nan)
    supply_strength = flow_20 / mcap_proxy
    supply = cross_sectional_percentile(supply_strength)

    # ---------- 밸류에이션 적정성 (섹터 내 백분위, 역방향) ----------
    per = md.fin("per")
    pbr = md.fin("pbr")
    # 비쌀수록 페널티: cheapness = 1 - percentile(비쌈)
    expensive = _avg_percentile(
        [cross_sectional_percentile(per), cross_sectional_percentile(pbr)]
    )
    valuation_cheapness = 1.0 - expensive

    return FactorPanel(
        trend=trend,
        relative_strength=relative_strength,
        quality=quality,
        supply=supply,
        valuation_cheapness=valuation_cheapness,
        raw={
            "ma_alignment": align,
            "atr": ta.atr(md, 14),
            "avg_turnover": ta.avg_turnover(md.value, 20),
            "ma120": ta.moving_average(close, 120),
            "ma20": ta.moving_average(close, 20),
            "ma60": ta.moving_average(close, 60),
            "rs_market_pct": cross_sectional_percentile(rs_market),
            "high52_window_max": close.rolling(60, min_periods=30).max(),
            "vol_avg20": md.volume.rolling(20, min_periods=10).mean(),
        },
    )
