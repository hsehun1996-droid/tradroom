"""팩터/피처 엔진 (블루프린트 C, 5장).

가격→기술적지표, 재무→퀄리티/밸류, 수급/추정치 가공.
모든 팩터는 횡단면 백분위(percentile) 또는 z-score 로 정규화하고
극단값은 윈저라이즈한다 — 서로 다른 단위를 합산하기 위해.
"""
from tradroom.features.engine import FactorPanel, build_factor_panel

__all__ = ["FactorPanel", "build_factor_panel"]
