"""데이터 적재 — Phase 0.  소스에서 받아 Parquet 으로 저장.

사용:
  python scripts/run_ingest.py --source sample
  TRADROOM_USE_LIVE_DATA=true python scripts/run_ingest.py --source live --start 2021-01-01
"""
from __future__ import annotations

import argparse

from tradroom.config import SETTINGS
from tradroom.data import load_market_data
from tradroom.data.storage import save_market_data


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="sample", choices=["sample", "live"])
    ap.add_argument("--start", default="2021-01-01")
    ap.add_argument("--end", default=None)
    args = ap.parse_args()

    SETTINGS.ensure_dirs()
    print(f"[ingest] source={args.source} ...")
    kwargs = {"start": args.start}
    if args.end:
        kwargs["end"] = args.end
    md = load_market_data(source=args.source, **kwargs)
    save_market_data(md)
    print(f"[ingest] 저장 완료 → {SETTINGS.data_dir}")
    print(f"[ingest] {len(md.tickers)} 종목, {md.dates[0].date()} ~ {md.dates[-1].date()}")


if __name__ == "__main__":
    main()
