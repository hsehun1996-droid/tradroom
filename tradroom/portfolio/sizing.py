"""Layer 5 — 포지션 사이징 & 리스크.

수익은 종목 선택이, 생존은 사이징이 만든다.
- 고정 분율 리스크: 매수금액 = (총자산 × 리스크%) / (손절폭%)
- 변동성 타기팅: 손절폭을 ATR 로 산정 → 변동성 큰 종목은 자연히 작게.
- 한도(Caps): 종목당/섹터당 최대 비중.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from tradroom.config import STRATEGY


@dataclass
class PositionPlan:
    ticker: str
    entry_price: float
    stop_price: float
    stop_pct: float          # 손절폭 (진입 대비)
    target_value: float      # 권장 매수금액
    shares: int
    weight: float            # 총자산 대비 비중
    reason: str


def position_size(
    ticker: str,
    entry_price: float,
    atr: float,
    total_equity: float,
    *,
    regime_exposure: float = 1.0,
    current_sector_weight: float = 0.0,
) -> PositionPlan:
    r = STRATEGY.risk
    # 손절 = 진입 - atr_stop_mult * ATR
    stop_price = max(0.01, entry_price - r.atr_stop_mult * atr)
    stop_pct = (entry_price - stop_price) / entry_price
    if stop_pct <= 0:
        stop_pct = 0.08  # 폴백 고정 손절

    # 고정 분율 리스크 → 매수금액
    risk_capital = total_equity * r.risk_per_trade
    target_value = risk_capital / stop_pct

    # 한도 적용: 종목당 비중, 레짐 노출
    cap_name = total_equity * r.max_weight_per_name
    cap_sector = max(0.0, total_equity * r.max_weight_per_sector - current_sector_weight * total_equity)
    target_value = min(target_value, cap_name, cap_sector, total_equity * regime_exposure)
    target_value = max(0.0, target_value)

    shares = int(target_value // entry_price)
    actual_value = shares * entry_price
    weight = actual_value / total_equity if total_equity else 0.0

    return PositionPlan(
        ticker=ticker,
        entry_price=round(entry_price, 2),
        stop_price=round(stop_price, 2),
        stop_pct=round(stop_pct, 4),
        target_value=round(actual_value, 0),
        shares=shares,
        weight=round(weight, 4),
        reason=f"리스크 {r.risk_per_trade:.1%}/거래, 손절폭 {stop_pct:.1%}, ATR×{r.atr_stop_mult}",
    )
