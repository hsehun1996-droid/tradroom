"""로더 — 라이브/샘플/디스크 소스를 하나로 묶는 진입점.

우선순위:
  1) source="sample"  → 합성 데이터 (기본, 키 불필요)
  2) source="disk"    → 이미 적재된 Parquet
  3) source="live"    → 실제 무료 API (pykrx/FDR/DART/ECOS/FRED)
  4) source="auto"    → use_live_data 설정에 따라 live, 실패 시 sample 로 폴백
"""
from __future__ import annotations

import logging

from tradroom.config import SETTINGS
from tradroom.data.base import MarketData
from tradroom.data.sample import generate_sample
from tradroom.data.storage import disk_cache_exists, load_market_data_from_disk

log = logging.getLogger(__name__)


def load_market_data(source: str = "auto", **kwargs) -> MarketData:
    if source == "sample":
        return generate_sample(**kwargs)

    if source == "disk":
        return load_market_data_from_disk()

    if source == "live":
        from tradroom.data.live import fetch_live_market_data

        return fetch_live_market_data(**kwargs)

    # auto
    if SETTINGS.use_live_data:
        try:
            from tradroom.data.live import fetch_live_market_data

            return fetch_live_market_data(**kwargs)
        except Exception as exc:  # 네트워크/키 문제 → 폴백
            log.warning("라이브 데이터 실패(%s) → 샘플 데이터로 폴백", exc)
    if disk_cache_exists():
        return load_market_data_from_disk()
    return generate_sample(**kwargs)
