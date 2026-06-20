"""시그널/스코어링 레이어 (블루프린트 D).

레짐 판정 → 섹터 RS → 종목 종합점수 → 게이트 → 랭킹.
"""
from tradroom.signals.regime import RegimeState, compute_regime
from tradroom.signals.sector import leading_sectors
from tradroom.signals.scoring import score_universe
from tradroom.signals.timing import entry_timing

__all__ = [
    "RegimeState",
    "compute_regime",
    "leading_sectors",
    "score_universe",
    "entry_timing",
]
