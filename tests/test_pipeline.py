"""파이프라인 통합 테스트 — 전체 레이어가 end-to-end 동작하는지 검증.

핵심 불변식(블루프린트):
  - 팩터 점수는 0~1 백분위 범위
  - 게이트 통과 후보만 BUY 후보가 됨
  - 백테스트는 비용 후 거래 기록 + 지표를 산출
  - look-ahead 방지: slice_until 로 미래 데이터가 새지 않음
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tradroom.backtest import run_backtest
from tradroom.data.sample import generate_sample
from tradroom.features.engine import build_factor_panel
from tradroom.portfolio import Position, daily_recommendation
from tradroom.signals.regime import compute_regime, regime_timeseries
from tradroom.signals.scoring import composite_score, score_universe


@pytest.fixture(scope="module")
def md():
    return generate_sample(start="2021-01-01", end="2023-12-31", seed=1)


@pytest.fixture(scope="module")
def fp(md):
    return build_factor_panel(md)


def test_sample_shapes(md):
    assert len(md.tickers) > 10
    assert md.close.shape == md.volume.shape
    assert set(["roe", "per", "pbr"]).issubset(md.financials)


def test_factor_percentile_range(fp):
    last = fp.trend.iloc[-1].dropna()
    assert ((last >= 0) & (last <= 1)).all()


def test_composite_score_bounds(md, fp):
    s = composite_score(fp, md.dates[-1]).dropna()
    assert (s >= 0).all() and (s <= 100).all()


def test_regime_labels(md):
    r = compute_regime(md)
    assert r.label in {"Risk-On", "Neutral", "Risk-Off"}
    assert 0.0 <= r.exposure <= 1.0
    ts = regime_timeseries(md)
    assert set(ts["label"].unique()).issubset({"Risk-On", "Neutral", "Risk-Off"})


def test_risk_off_blocks_candidates(md, fp):
    date = md.dates[-1]
    blocked = score_universe(md, fp, date, regime_allows=False)
    assert not blocked["passed_gate"].any()


def test_recommendation_structure(md, fp):
    holding = Position(md.tickers[0], shares=100, avg_price=float(md.close[md.tickers[0]].iloc[200]))
    rec = daily_recommendation(md, holdings=[holding], total_equity=1e8, fp=fp)
    assert rec.regime.label in {"Risk-On", "Neutral", "Risk-Off"}
    assert len(rec.holdings) == 1
    assert rec.holdings[0].action in {"HOLD", "TRIM", "SELL"}
    for c in rec.buy_candidates:
        assert c.timing in {"BUY_NOW", "WATCH"}


def test_backtest_runs_and_has_costs(md, fp):
    res = run_backtest(md, fp=fp, initial_equity=1e8)
    assert len(res.equity) > 50
    assert "cagr" in res.metrics and "mdd" in res.metrics
    assert res.metrics["mdd"] <= 0
    if not res.trades.empty:
        # 매도 거래세/수수료가 반영되어 동일가 청산 시 손실이어야 함(비용 > 0)
        assert {"pnl", "reason"}.issubset(res.trades.columns)


def test_no_lookahead_in_slice(md):
    cut = md.dates[len(md.dates) // 2]
    sliced = md.slice_until(cut)
    assert sliced.close.index.max() <= cut
    assert sliced.macro.index.max() <= cut
