"""중앙 설정 — 환경변수, 저장소 경로, 전략 파라미터.

블루프린트 원칙: 자유 파라미터가 많을수록 과적합 위험이 커진다.
모든 임계치/가중치/룩백을 여기 한 곳에 모아 "단순하게 시작, 백테스트로 검증" 한다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # python-dotenv 미설치 시에도 동작
    pass


def _env_bool(key: str, default: bool = False) -> bool:
    return os.getenv(key, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # --- 데이터 소스 ---
    use_live_data: bool = _env_bool("TRADROOM_USE_LIVE_DATA", False)
    dart_api_key: str = os.getenv("DART_API_KEY", "")
    ecos_api_key: str = os.getenv("ECOS_API_KEY", "")
    fred_api_key: str = os.getenv("FRED_API_KEY", "")

    # --- 저장소 ---
    data_dir: Path = Path(os.getenv("TRADROOM_DATA_DIR", "./data_store")).resolve()

    def ensure_dirs(self) -> None:
        for sub in ("prices", "flows", "financials", "macro", "meta", "results"):
            (self.data_dir / sub).mkdir(parents=True, exist_ok=True)


# =====================================================================
# 전략 파라미터 (블루프린트 4~6장)
# =====================================================================
@dataclass(frozen=True)
class RegimeParams:
    """Layer 1 — 매크로 레짐. 단순 점수제(과적합 방지). 각 지표 +1/0/-1 합산."""

    ma_window: int = 200            # KOSPI vs MA200
    risk_on_threshold: int = 2      # 합산 >= +2 → Risk-On
    risk_off_threshold: int = -2    # 합산 <= -2 → Risk-Off
    # 총노출(gross exposure): 레짐별로 엑셀러레이터를 얼마나 밟을지
    exposure_on: float = 1.00
    exposure_neutral: float = 0.60
    exposure_off: float = 0.00


@dataclass(frozen=True)
class SectorParams:
    """Layer 2 — 섹터 로테이션. RS 상위만 사냥터로."""

    rs_lookback_short: int = 63     # ~3M (거래일)
    rs_lookback_long: int = 126     # ~6M
    ma_window: int = 60
    w_short: float = 0.4
    w_long: float = 0.4
    w_trend: float = 0.2
    top_quantile: float = 0.30      # 상위 30% 섹터만 활성


@dataclass(frozen=True)
class FactorWeights:
    """Layer 3 — 멀티팩터 종합점수 가중치 (블루프린트 4.3)."""

    trend: float = 0.35
    relative_strength: float = 0.20
    quality: float = 0.20
    supply: float = 0.15
    valuation: float = 0.10         # 비쌀수록 감점(역방향)


@dataclass(frozen=True)
class GateParams:
    """Layer 3 (A) — 하드 게이트. 하나라도 실패하면 후보 탈락."""

    min_turnover_krw: float = 5e9   # 20일 평균 거래대금 >= 50억
    turnover_window: int = 20
    trend_ma_window: int = 120      # 종가 > MA120
    min_ma_alignment: int = 3       # MA정배열점수 >= 3 (0~4)


@dataclass(frozen=True)
class TimingParams:
    """Layer 4 — 진입 타이밍."""

    breakout_window: int = 60       # N일 신고가 돌파
    volume_mult: float = 1.5        # 거래량 평균 대비
    pullback_ma: int = 20
    overextension_pct: float = 0.15 # MA20 대비 +15% 이상 이격이면 과열 → WATCH


@dataclass(frozen=True)
class RiskParams:
    """Layer 5 — 사이징 & 리스크."""

    risk_per_trade: float = 0.01    # 거래당 총자산의 1% 리스크
    atr_window: int = 14
    atr_stop_mult: float = 2.0      # 손절 = 진입 - 2*ATR
    max_weight_per_name: float = 0.12
    max_weight_per_sector: float = 0.35
    target_positions: int = 15      # 상위 K개 보유 목표


@dataclass(frozen=True)
class ExitParams:
    """Layer 6 — 청산 규칙."""

    trailing_stop_pct: float = 0.15 # 고점 대비 -15%
    exit_ma_window: int = 60        # 종가가 MA60 하향이탈
    rs_exit_rank: float = 0.40      # RS 랭크가 하위 40%로 추락


@dataclass(frozen=True)
class RotateParams:
    """Layer 7 — 교체. 마찰(임계치)로 잦은 교체 억제."""

    score_gap_threshold: float = 10.0  # 신규 후보가 보유 +10점 초과 + 보유 약화 시만 교체


@dataclass(frozen=True)
class CostParams:
    """백테스트 비용 모델 — 한국 시장(거래세는 매도에만)."""

    commission: float = 0.00015     # 매수/매도 수수료 (편도)
    sell_tax: float = 0.0015        # 매도 시 증권거래세 (시점 재확인 필요)
    slippage: float = 0.001         # 슬리피지


@dataclass(frozen=True)
class StrategyConfig:
    regime: RegimeParams = field(default_factory=RegimeParams)
    sector: SectorParams = field(default_factory=SectorParams)
    weights: FactorWeights = field(default_factory=FactorWeights)
    gate: GateParams = field(default_factory=GateParams)
    timing: TimingParams = field(default_factory=TimingParams)
    risk: RiskParams = field(default_factory=RiskParams)
    exit: ExitParams = field(default_factory=ExitParams)
    rotate: RotateParams = field(default_factory=RotateParams)
    cost: CostParams = field(default_factory=CostParams)


SETTINGS = Settings()
STRATEGY = StrategyConfig()
