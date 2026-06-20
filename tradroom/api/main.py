"""FastAPI 서버 — 대시보드용 읽기 전용 API.

설계 규칙(블루프린트 G): 화면은 읽기 전용 뷰.  모든 계산은 signal/backtest/
portfolio 레이어에서 끝나고, API 는 결과만 직렬화한다.

엔드포인트:
  GET  /api/health
  GET  /api/regime              레짐 신호등
  GET  /api/sectors             섹터 RS 로테이션
  GET  /api/candidates          매수 후보 (BUY_NOW/WATCH)
  POST /api/portfolio           보유 입력 → 진단 + 교체 추천
  GET  /api/backtest            백테스트 성과 + 자산곡선
"""
from __future__ import annotations

from dataclasses import asdict
from functools import lru_cache

import pandas as pd
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from tradroom.backtest import run_backtest
from tradroom.data import load_market_data
from tradroom.features.engine import build_factor_panel
from tradroom.portfolio import Position, daily_recommendation
from tradroom.signals.regime import compute_regime
from tradroom.signals.sector import sector_rs_table

app = FastAPI(title="tradroom API", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


@lru_cache(maxsize=1)
def _ctx():
    md = load_market_data(source="auto")
    fp = build_factor_panel(md)
    return md, fp


@lru_cache(maxsize=1)
def _backtest():
    md, fp = _ctx()
    return run_backtest(md, fp=fp)


# --------------------------------------------------------------------- models
class HoldingIn(BaseModel):
    ticker: str
    shares: int
    avg_price: float


class PortfolioIn(BaseModel):
    holdings: list[HoldingIn] = []
    total_equity: float = 1e8


# --------------------------------------------------------------------- routes
@app.get("/api/health")
def health():
    md, _ = _ctx()
    return {"status": "ok", "tickers": len(md.tickers),
            "start": str(md.dates[0].date()), "end": str(md.dates[-1].date())}


@app.get("/api/regime")
def regime():
    md, _ = _ctx()
    r = compute_regime(md)
    return {"date": str(r.date.date()), "label": r.label, "score": r.score,
            "exposure": r.exposure, "components": r.components,
            "allow_new_entry": r.allow_new_entry}


@app.get("/api/sectors")
def sectors():
    md, _ = _ctx()
    tbl = sector_rs_table(md, md.dates[-1]).reset_index()
    tbl.columns = ["sector", "ret_short", "ret_long", "above_ma", "rs_score"]
    from tradroom.signals.sector import leading_sectors

    active = set(leading_sectors(md, md.dates[-1]))
    tbl["active"] = tbl["sector"].isin(active)
    return tbl.round(4).to_dict(orient="records")


@app.get("/api/candidates")
def candidates(top: int = 20):
    md, fp = _ctx()
    rec = daily_recommendation(md, total_equity=1e8, top_k=top, fp=fp)
    return [_candidate_dict(c) for c in rec.buy_candidates]


@app.post("/api/portfolio")
def portfolio(body: PortfolioIn):
    md, fp = _ctx()
    holdings = [Position(h.ticker, h.shares, h.avg_price) for h in body.holdings]
    rec = daily_recommendation(md, holdings=holdings, total_equity=body.total_equity, fp=fp)
    return {
        "date": rec.date,
        "regime": {"label": rec.regime.label, "score": rec.regime.score,
                   "exposure": rec.regime.exposure},
        "holdings": [asdict(h) for h in rec.holdings],
        "rotations": [asdict(r) for r in rec.rotations],
        "candidates": [_candidate_dict(c) for c in rec.buy_candidates],
    }


@app.get("/api/backtest")
def backtest():
    res = _backtest()
    eq = res.equity
    # 다운샘플(주간) — 프론트 차트 경량화
    eq_w = eq.resample("W").last().dropna()
    dd = (eq_w / eq_w.cummax() - 1)
    return {
        "metrics": res.metrics,
        "equity": [{"date": str(d.date()), "value": round(v, 0)} for d, v in eq_w.items()],
        "drawdown": [{"date": str(d.date()), "value": round(v, 4)} for d, v in dd.items()],
        "trades": res.trades.tail(50).assign(
            entry_date=lambda d: d["entry_date"].astype(str),
            exit_date=lambda d: d["exit_date"].astype(str),
        ).to_dict(orient="records"),
    }


def _candidate_dict(c) -> dict:
    d = {"ticker": c.ticker, "name": c.name, "sector": c.sector, "score": c.score,
         "timing": c.timing, "timing_reason": c.timing_reason, "factors": c.factors}
    if c.plan:
        d["plan"] = {"shares": c.plan.shares, "target_value": c.plan.target_value,
                     "entry_price": c.plan.entry_price, "stop_price": c.plan.stop_price,
                     "stop_pct": c.plan.stop_pct, "weight": c.plan.weight}
    return d
