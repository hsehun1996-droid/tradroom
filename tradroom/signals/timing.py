"""Layer 4 — 진입 타이밍.

좋은 종목 ≠ 지금 사는 종목.  돌파/눌림 + 거래량 동반을 보고,
과열(MA20 대비 과대 이격)이면 'WATCH' 로만 표시.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from tradroom.config import STRATEGY
from tradroom.data.base import MarketData
from tradroom.features.engine import FactorPanel


@dataclass
class TimingSignal:
    label: str       # "BUY_NOW" | "WATCH"
    reason: str


def entry_timing(
    md: MarketData, fp: FactorPanel, ticker: str, date: pd.Timestamp
) -> TimingSignal:
    p = STRATEGY.timing
    close = md.close[ticker]
    price = close.loc[date]
    ma20 = fp.raw["ma20"][ticker].loc[date]

    # 과열: MA20 대비 +overextension% 이상 이격 → WATCH
    if pd.notna(ma20) and ma20 > 0 and (price / ma20 - 1) > p.overextension_pct:
        return TimingSignal("WATCH", f"과열(MA20 대비 +{(price/ma20-1)*100:.0f}%) — 진입 보류")

    # 돌파: 최근 N일 신고가 + 거래량 동반
    window_high = md.close[ticker].rolling(p.breakout_window, min_periods=p.breakout_window // 2)\
        .max().shift(1).loc[date]
    vol = md.volume[ticker].loc[date]
    vol_avg = fp.raw["vol_avg20"][ticker].loc[date]
    volume_ok = pd.notna(vol_avg) and vol_avg > 0 and vol >= p.volume_mult * vol_avg

    if pd.notna(window_high) and price >= window_high and volume_ok:
        return TimingSignal("BUY_NOW", f"{p.breakout_window}일 신고가 돌파 + 거래량 동반")

    # 눌림 후 반등: MA20 근처(±3%)에서 반등 캔들 + 정배열
    near_ma20 = pd.notna(ma20) and abs(price / ma20 - 1) <= 0.03
    rebound = close.loc[date] > close.shift(1).loc[date]
    align = fp.raw["ma_alignment"][ticker].loc[date]
    if near_ma20 and rebound and align >= 3:
        return TimingSignal("BUY_NOW", "정배열 + MA20 눌림 후 반등")

    return TimingSignal("WATCH", "진입 자리 대기(돌파/눌림 미충족)")
