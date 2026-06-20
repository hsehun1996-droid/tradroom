"""데이터 레이어 — 수집(Ingestion) · 저장(Storage) · 표준 컨테이너.

설계 규칙(블루프린트 C): *반드시 point-in-time* — 그 시점에 알 수 있던 값만.
재무는 DART 접수일(rcept_dt) 기준으로 사용한다(look-ahead 방지).
"""
from tradroom.data.base import MarketData
from tradroom.data.loader import load_market_data

__all__ = ["MarketData", "load_market_data"]
