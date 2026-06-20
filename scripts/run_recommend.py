"""일일 추천 실행 — 보유 종목 입력 → 매수후보 + 보유진단 + 교체추천.

보유는 JSON 파일로 입력:
  [{"ticker": "000105", "shares": 100, "avg_price": 50000}, ...]

사용:
  python scripts/run_recommend.py
  python scripts/run_recommend.py --holdings my_portfolio.json --equity 50000000
"""
from __future__ import annotations

import argparse
import json

from tradroom.config import SETTINGS
from tradroom.data import load_market_data
from tradroom.portfolio import Position, daily_recommendation


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="auto")
    ap.add_argument("--holdings", default=None, help="보유 종목 JSON 파일")
    ap.add_argument("--equity", type=float, default=1e8)
    ap.add_argument("--top", type=int, default=15)
    args = ap.parse_args()

    SETTINGS.ensure_dirs()
    md = load_market_data(source=args.source)

    holdings = []
    if args.holdings:
        for h in json.loads(open(args.holdings).read()):
            holdings.append(Position(h["ticker"], int(h["shares"]), float(h["avg_price"])))

    rec = daily_recommendation(md, holdings=holdings, total_equity=args.equity, top_k=args.top)

    r = rec.regime
    print(f"\n📅 {rec.date}")
    print(f"🚦 레짐: {r.label} (score={r.score:+d}, 허용노출={r.exposure:.0%})  {r.components}")

    print("\n🟢 매수 후보 (BUY_NOW / WATCH)")
    for c in rec.buy_candidates:
        tag = "🟢 BUY" if c.timing == "BUY_NOW" else "👀 WATCH"
        sz = f" | {c.plan.shares}주 ~{c.plan.target_value:,.0f}원 (손절 {c.plan.stop_price:,.0f})" if c.plan else ""
        print(f"  {tag} [{c.sector}] {c.name}({c.ticker}) 점수 {c.score:.0f} — {c.timing_reason}{sz}")

    if rec.holdings:
        print("\n📊 보유 종목 건강검진")
        icon = {"HOLD": "🟢", "TRIM": "🟡", "SELL": "🔴"}
        for h in rec.holdings:
            print(f"  {icon.get(h.action,'')} {h.action} {h.name}({h.ticker}) "
                  f"점수 {h.score:.0f}, 수익 {h.pnl_pct:+.1f}% — {', '.join(h.triggers) or '훼손신호 없음'}")

    if rec.rotations:
        print("\n🔄 교체 추천 (마찰 임계치 통과)")
        for ro in rec.rotations:
            print(f"  {ro.sell_name} → {ro.buy_name}: {ro.reason}")


if __name__ == "__main__":
    main()
