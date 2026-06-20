"""저장소 — wide 패널을 Parquet 으로 저장/로드.

블루프린트 B: 시계열은 Parquet(또는 TimescaleDB).  여기서는 단순 Parquet.
규모가 커지면 동일 인터페이스 뒤에서 TimescaleDB 로 교체 가능.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from tradroom.config import SETTINGS
from tradroom.data.base import MarketData

_PANELS = ["open", "high", "low", "close", "volume", "value", "net_flow"]


def save_market_data(md: MarketData, data_dir: Path | None = None) -> None:
    root = Path(data_dir) if data_dir else SETTINGS.data_dir
    root.mkdir(parents=True, exist_ok=True)
    for name in _PANELS:
        getattr(md, name).to_parquet(root / f"{name}.parquet")
    for metric, df in md.financials.items():
        df.to_parquet(root / f"fin_{metric}.parquet")
    md.meta.to_parquet(root / "meta.parquet")
    md.macro.to_parquet(root / "macro.parquet")
    md.sector_index.to_parquet(root / "sector_index.parquet")
    (root / "manifest.json").write_text(
        json.dumps({"financials": list(md.financials.keys())}, ensure_ascii=False, indent=2)
    )


def load_market_data_from_disk(data_dir: Path | None = None) -> MarketData:
    root = Path(data_dir) if data_dir else SETTINGS.data_dir
    manifest = json.loads((root / "manifest.json").read_text())
    panels = {name: pd.read_parquet(root / f"{name}.parquet") for name in _PANELS}
    financials = {m: pd.read_parquet(root / f"fin_{m}.parquet") for m in manifest["financials"]}
    return MarketData(
        **panels,
        financials=financials,
        meta=pd.read_parquet(root / "meta.parquet"),
        macro=pd.read_parquet(root / "macro.parquet"),
        sector_index=pd.read_parquet(root / "sector_index.parquet"),
    )


def disk_cache_exists(data_dir: Path | None = None) -> bool:
    root = Path(data_dir) if data_dir else SETTINGS.data_dir
    return (root / "manifest.json").exists()
