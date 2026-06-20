"""백테스트 엔진 (블루프린트 E) — ★성패의 90%★.

look-ahead/생존편향/비용/유동성 반영, 워크포워드 검증.
팩터 패널은 trailing 윈도우만 사용하므로 as_of(date) 슬라이스가 point-in-time.
"""
from tradroom.backtest.engine import BacktestResult, run_backtest
from tradroom.backtest.metrics import performance_metrics
from tradroom.backtest.walkforward import walk_forward

__all__ = ["BacktestResult", "run_backtest", "performance_metrics", "walk_forward"]
