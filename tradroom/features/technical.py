"""기술적 지표 — 이동평균, 모멘텀, 정배열, 52주고가, ATR, ADX.

블루프린트 5장(추세·모멘텀)·4.5(ATR 사이징).  모두 wide 패널 입력/출력.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from tradroom.data.base import MarketData


def moving_average(close: pd.DataFrame, window: int) -> pd.DataFrame:
    return close.rolling(window, min_periods=window // 2).mean()


def momentum(close: pd.DataFrame, lookback: int, skip: int = 0) -> pd.DataFrame:
    """P[t-skip] / P[t-skip-lookback] - 1.  skip>0 으로 단기반전 노이즈 제거."""
    return close.shift(skip) / close.shift(skip + lookback) - 1.0


def ma_alignment_score(close: pd.DataFrame) -> pd.DataFrame:
    """MA 정배열점수 0~4: (P>MA20)+(MA20>MA60)+(MA60>MA120)+(MA120>MA200)."""
    ma20 = moving_average(close, 20)
    ma60 = moving_average(close, 60)
    ma120 = moving_average(close, 120)
    ma200 = moving_average(close, 200)
    score = (
        (close > ma20).astype(float)
        + (ma20 > ma60).astype(float)
        + (ma60 > ma120).astype(float)
        + (ma120 > ma200).astype(float)
    )
    return score


def high_proximity_52w(close: pd.DataFrame, window: int = 252) -> pd.DataFrame:
    """52주 고가 근접도: P / max(최근 252일).  1에 가까울수록 강세."""
    roll_max = close.rolling(window, min_periods=window // 2).max()
    return close / roll_max


def atr(md: MarketData, window: int = 14) -> pd.DataFrame:
    """Average True Range (wide)."""
    prev_close = md.close.shift(1)
    tr = pd.concat(
        [
            (md.high - md.low),
            (md.high - prev_close).abs(),
            (md.low - prev_close).abs(),
        ]
    )
    # 위 concat 은 행축으로 쌓이므로 element-wise max 를 위해 재구성
    tr = pd.DataFrame(
        np.maximum.reduce(
            [
                (md.high - md.low).to_numpy(),
                (md.high - prev_close).abs().to_numpy(),
                (md.low - prev_close).abs().to_numpy(),
            ]
        ),
        index=md.close.index,
        columns=md.close.columns,
    )
    return tr.rolling(window, min_periods=window // 2).mean()


def adx(md: MarketData, window: int = 14) -> pd.DataFrame:
    """ADX (추세 강도).  횡보장 필터용.  벡터화 근사 구현."""
    up_move = md.high.diff()
    down_move = -md.low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    tr = atr(md, window)  # ATR 을 TR 평활 대용으로 사용
    atr_safe = tr.replace(0, np.nan)
    plus_di = 100 * plus_dm.rolling(window).mean() / atr_safe
    minus_di = 100 * minus_dm.rolling(window).mean() / atr_safe
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.rolling(window).mean()


def avg_turnover(value: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """20일 평균 거래대금 — 유동성 게이트용."""
    return value.rolling(window, min_periods=window // 2).mean()
