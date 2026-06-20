"""백테스트 실행 — Phase 1 ★최우선★.

사용:
  python scripts/run_backtest.py            # 샘플 데이터
  TRADROOM_USE_LIVE_DATA=true python scripts/run_backtest.py --source live
"""
from __future__ import annotations

import argparse
import json

from tradroom.backtest import run_backtest, walk_forward
from tradroom.config import SETTINGS
from tradroom.data import load_market_data


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="auto", choices=["auto", "sample", "live", "disk"])
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--equity", type=float, default=1e8)
    ap.add_argument("--walkforward", action="store_true")
    args = ap.parse_args()

    SETTINGS.ensure_dirs()
    print(f"[data] source={args.source} loading...")
    md = load_market_data(source=args.source)
    print(f"[data] {len(md.tickers)} 종목, {md.dates[0].date()} ~ {md.dates[-1].date()}")

    res = run_backtest(md, start=args.start, end=args.end, initial_equity=args.equity)
    print("\n===== 백테스트 성과 (비용·슬리피지·유동성·look-ahead 반영) =====")
    print(json.dumps(res.metrics, indent=2, ensure_ascii=False))

    if not res.trades.empty:
        print("\n----- 최근 거래 10건 -----")
        print(res.trades.tail(10).to_string(index=False))

    out = SETTINGS.data_dir / "results"
    out.mkdir(parents=True, exist_ok=True)
    res.equity.to_frame("equity").to_csv(out / "equity_curve.csv")
    res.trades.to_csv(out / "trades.csv", index=False)
    (out / "metrics.json").write_text(json.dumps(res.metrics, indent=2, ensure_ascii=False))
    print(f"\n[saved] {out}/equity_curve.csv, trades.csv, metrics.json")

    if args.walkforward:
        print("\n===== 워크포워드 (아웃오브샘플 robust 점검) =====")
        wf = walk_forward(md)
        print(wf.to_string(index=False))
        wf.to_csv(out / "walkforward.csv", index=False)


if __name__ == "__main__":
    main()
