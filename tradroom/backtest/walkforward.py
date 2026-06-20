"""워크포워드 검증 (블루프린트 7장).

과거 구간에서 정하고, *그 다음 미지의 구간*에서 평가.  여기서는 파라미터
탐색 없이 롤링 아웃오브샘플 성과를 분할 측정해 robust 여부를 본다
(파라미터 최적화는 과적합 위험이 커 별도 신중히).
"""
from __future__ import annotations

import pandas as pd

from tradroom.backtest.engine import run_backtest
from tradroom.backtest.metrics import performance_metrics
from tradroom.data.base import MarketData
from tradroom.features.engine import build_factor_panel


def walk_forward(
    md: MarketData,
    n_splits: int = 4,
    initial_equity: float = 1e8,
) -> pd.DataFrame:
    fp = build_factor_panel(md)
    dates = md.dates
    warmup = 252
    usable = dates[warmup:]
    if len(usable) < n_splits * 30:
        n_splits = max(1, len(usable) // 60)

    bounds = pd.date_range(usable[0], usable[-1], periods=n_splits + 1)
    rows = []
    for k in range(n_splits):
        s, e = bounds[k], bounds[k + 1]
        res = run_backtest(md, start=str(s.date()), end=str(e.date()),
                           initial_equity=initial_equity, fp=fp, warmup=0)
        m = res.metrics
        rows.append(
            {
                "split": k + 1, "start": str(s.date()), "end": str(e.date()),
                "cagr": m.get("cagr"), "mdd": m.get("mdd"),
                "sharpe": m.get("sharpe"), "sortino": m.get("sortino"),
                "n_trades": m.get("n_trades"), "win_rate": m.get("win_rate"),
                "payoff_ratio": m.get("payoff_ratio"),
            }
        )
    return pd.DataFrame(rows)
