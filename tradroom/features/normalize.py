"""횡단면 정규화 — winsorize · percentile · z-score.

블루프린트 5장: 모든 팩터는 유니버스 내 횡단면 백분위 또는 z-score 로
정규화하고, 극단값은 1/99%에서 윈저라이즈.
"""
from __future__ import annotations

import pandas as pd


def winsorize_row(row: pd.Series, lower: float = 0.01, upper: float = 0.99) -> pd.Series:
    valid = row.dropna()
    if valid.empty:
        return row
    lo, hi = valid.quantile(lower), valid.quantile(upper)
    return row.clip(lower=lo, upper=hi)


def cross_sectional_percentile(df: pd.DataFrame) -> pd.DataFrame:
    """각 날짜(행)에서 종목 간 백분위(0~1).  높을수록 좋음 가정."""
    w = df.apply(winsorize_row, axis=1)
    return w.rank(axis=1, pct=True)


def cross_sectional_zscore(df: pd.DataFrame) -> pd.DataFrame:
    w = df.apply(winsorize_row, axis=1)
    mean = w.mean(axis=1)
    std = w.std(axis=1).replace(0, pd.NA)
    return w.sub(mean, axis=0).div(std, axis=0)
