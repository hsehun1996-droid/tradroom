"""Layer 2 — 섹터/테마 로테이션 (사냥터 좁히기).

KRX 업종지수별 상대강도(RS) 계산 → 상위 N% 만 "활성 사냥터".
하위 섹터 종목은 개별 점수가 좋아도 신규매수 제외(역추세 함정 회피).
"""
from __future__ import annotations

import pandas as pd

from tradroom.config import STRATEGY
from tradroom.data.base import MarketData


def sector_rs_table(md: MarketData, date: pd.Timestamp) -> pd.DataFrame:
    """date 기준 섹터별 RS 점수 표 (정렬됨)."""
    p = STRATEGY.sector
    si = md.sector_index.loc[md.sector_index.index <= date]
    if len(si) < p.rs_lookback_long + 5:
        # 데이터 부족 시 단기만
        lb_s = min(p.rs_lookback_short, len(si) - 2)
        lb_l = min(p.rs_lookback_long, len(si) - 2)
    else:
        lb_s, lb_l = p.rs_lookback_short, p.rs_lookback_long

    last = si.iloc[-1]
    ret_s = last / si.iloc[-1 - lb_s] - 1
    ret_l = last / si.iloc[-1 - lb_l] - 1
    ma = si.rolling(p.ma_window, min_periods=p.ma_window // 2).mean().iloc[-1]
    above_ma = (last > ma).astype(float)

    rs = p.w_short * _rank(ret_s) + p.w_long * _rank(ret_l) + p.w_trend * above_ma
    tbl = pd.DataFrame(
        {"ret_short": ret_s, "ret_long": ret_l, "above_ma": above_ma, "rs_score": rs}
    ).sort_values("rs_score", ascending=False)
    return tbl


def _rank(s: pd.Series) -> pd.Series:
    return s.rank(pct=True)


def leading_sectors(md: MarketData, date: pd.Timestamp) -> list[str]:
    """활성 사냥터 = RS 상위 분위 섹터."""
    p = STRATEGY.sector
    tbl = sector_rs_table(md, date)
    n = max(1, round(len(tbl) * p.top_quantile))
    return tbl.head(n).index.tolist()
