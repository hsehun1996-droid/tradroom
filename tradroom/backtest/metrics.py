"""성과 지표 — CAGR, MDD, 샤프, 소르티노, 손익비, 승률(참고), 회전율.

블루프린트 7장: 우리가 진짜 관리하는 건 기대값·손익비·MDD·샤프/소르티노.
승률은 KPI 가 아니라 모니터링 지표.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def performance_metrics(equity: pd.Series, trades: pd.DataFrame | None = None) -> dict:
    equity = equity.dropna()
    if len(equity) < 2:
        return {}
    ret = equity.pct_change().dropna()
    years = (equity.index[-1] - equity.index[0]).days / 365.25 or 1e-9
    total_return = equity.iloc[-1] / equity.iloc[0] - 1
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1

    vol = ret.std() * np.sqrt(TRADING_DAYS)
    sharpe = (ret.mean() * TRADING_DAYS) / (vol + 1e-12)
    downside = ret[ret < 0].std() * np.sqrt(TRADING_DAYS)
    sortino = (ret.mean() * TRADING_DAYS) / (downside + 1e-12)

    cummax = equity.cummax()
    drawdown = equity / cummax - 1
    mdd = drawdown.min()

    metrics = {
        "total_return": round(float(total_return), 4),
        "cagr": round(float(cagr), 4),
        "vol": round(float(vol), 4),
        "sharpe": round(float(sharpe), 3),
        "sortino": round(float(sortino), 3),
        "mdd": round(float(mdd), 4),
        "calmar": round(float(cagr / (abs(mdd) + 1e-12)), 3),
        "n_days": int(len(equity)),
    }

    if trades is not None and not trades.empty and "pnl" in trades:
        wins = trades[trades["pnl"] > 0]["pnl"]
        losses = trades[trades["pnl"] <= 0]["pnl"]
        win_rate = len(wins) / len(trades)
        avg_win = wins.mean() if len(wins) else 0.0
        avg_loss = abs(losses.mean()) if len(losses) else 0.0
        payoff = (avg_win / avg_loss) if avg_loss else float("inf")
        expectancy = win_rate * avg_win - (1 - win_rate) * avg_loss
        metrics.update(
            {
                "n_trades": int(len(trades)),
                "win_rate": round(float(win_rate), 3),
                "payoff_ratio": round(float(payoff), 2),
                "expectancy": round(float(expectancy), 1),
            }
        )
    return metrics


def drawdown_series(equity: pd.Series) -> pd.Series:
    return equity / equity.cummax() - 1
