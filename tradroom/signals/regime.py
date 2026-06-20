"""Layer 1 — 매크로 레짐 필터 (위험 ON/OFF 신호등).

단순 점수제(과적합 방지): 각 지표 +1/0/-1 합산.  레짐은 *총노출*과
*신규진입 허용 여부*를 결정한다(종목 로직은 그대로).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from tradroom.config import STRATEGY
from tradroom.data.base import MarketData


@dataclass
class RegimeState:
    date: pd.Timestamp
    score: int
    label: str          # "Risk-On" | "Neutral" | "Risk-Off"
    exposure: float     # 허용 총노출 0~1
    components: dict     # 각 지표 기여(-1/0/+1)

    @property
    def allow_new_entry(self) -> bool:
        return self.label != "Risk-Off"


def _regime_score_series(md: MarketData) -> pd.DataFrame:
    """날짜별 레짐 구성요소 점수 패널."""
    p = STRATEGY.regime
    m = md.macro.copy()
    out = pd.DataFrame(index=m.index)

    # 1) 추세: KOSPI vs MA200
    ma = m["kospi_close"].rolling(p.ma_window, min_periods=p.ma_window // 2).mean()
    out["trend"] = np.sign(m["kospi_close"] - ma)

    # 2) 변동성: VKOSPI 수준/급등 → 높으면 -1
    vk = m["vkospi"]
    vk_hi = vk > vk.rolling(60, min_periods=20).mean() + vk.rolling(60, min_periods=20).std()
    out["volatility"] = np.where(vk_hi, -1.0, np.where(vk < 18, 1.0, 0.0))

    # 3) 환율: USD/KRW 급격 약세(원화 약세) → -1
    fx_chg = m["usdkrw"].pct_change(20)
    out["fx"] = np.where(fx_chg > 0.03, -1.0, np.where(fx_chg < -0.03, 1.0, 0.0))

    # 4) 글로벌 위험: 하이일드 스프레드 급확대 → -1
    hy = m["us_hy_spread"]
    hy_chg = hy.diff(20)
    out["global_risk"] = np.where(hy_chg > 0.5, -1.0, np.where(hy_chg < -0.5, 1.0, 0.0))

    # 5) 수급: 외국인 전체 순매수 추세
    fn = m["foreign_net"].rolling(20, min_periods=10).mean()
    out["supply"] = np.sign(fn).fillna(0.0)

    return out.fillna(0.0)


def regime_timeseries(md: MarketData) -> pd.DataFrame:
    """전체 기간 레짐(score/label/exposure) — 백테스트용."""
    p = STRATEGY.regime
    comp = _regime_score_series(md)
    score = comp.sum(axis=1)
    label = pd.Series("Neutral", index=score.index)
    label[score >= p.risk_on_threshold] = "Risk-On"
    label[score <= p.risk_off_threshold] = "Risk-Off"
    exposure = label.map(
        {"Risk-On": p.exposure_on, "Neutral": p.exposure_neutral, "Risk-Off": p.exposure_off}
    )
    return pd.DataFrame({"score": score, "label": label, "exposure": exposure})


def compute_regime(md: MarketData, date: pd.Timestamp | None = None) -> RegimeState:
    comp = _regime_score_series(md)
    date = date or comp.index[-1]
    row = comp.loc[date]
    score = int(row.sum())
    p = STRATEGY.regime
    if score >= p.risk_on_threshold:
        label, exposure = "Risk-On", p.exposure_on
    elif score <= p.risk_off_threshold:
        label, exposure = "Risk-Off", p.exposure_off
    else:
        label, exposure = "Neutral", p.exposure_neutral
    return RegimeState(
        date=date, score=score, label=label, exposure=exposure,
        components={k: int(v) for k, v in row.items()},
    )
