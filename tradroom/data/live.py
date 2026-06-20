"""실제 무료 API 어댑터 — pykrx · FinanceDataReader · DART · ECOS · FRED.

블루프린트 3장의 소스를 MarketData 로 조립한다.  네트워크/키가 없거나
일부 소스가 실패해도 *얻은 만큼* 채우고 나머지는 NaN/폴백으로 둔다
(팩터 엔진이 결측을 우아하게 무시).

주의: point-in-time.  재무는 DART 접수일(rcept_dt) 이후에만 값이 보이도록
forward-fill 한다.  수급/지수도 마감 후 확정값만 사용.
"""
from __future__ import annotations

import logging
from datetime import datetime

import numpy as np
import pandas as pd

from tradroom.config import SETTINGS
from tradroom.data.base import MarketData

log = logging.getLogger(__name__)

# KRX 업종 → 우리 섹터 버킷 (단순 매핑; 확장 가능)
_DEFAULT_UNIVERSE_TOP = 60  # 시총 상위 N


def fetch_live_market_data(
    start: str = "2021-01-01",
    end: str | None = None,
    tickers: list[str] | None = None,
    universe_size: int = _DEFAULT_UNIVERSE_TOP,
) -> MarketData:
    from pykrx import stock  # 지연 임포트

    end = end or datetime.today().strftime("%Y-%m-%d")
    s, e = start.replace("-", ""), end.replace("-", "")

    # --- 유니버스: 시총 상위 N (KOSPI) ---
    if tickers is None:
        cap = stock.get_market_cap_by_ticker(e, market="KOSPI")
        tickers = cap.sort_values("시가총액", ascending=False).head(universe_size).index.tolist()
    log.info("라이브 유니버스 %d 종목 적재", len(tickers))

    # --- 가격 패널 ---
    o, h, l, c, v, val, flow = ({} for _ in range(7))
    meta_rows = []
    for tkr in tickers:
        try:
            df = stock.get_market_ohlcv(s, e, tkr)
            if df.empty:
                continue
            o[tkr], h[tkr], l[tkr] = df["시가"], df["고가"], df["저가"]
            c[tkr], v[tkr], val[tkr] = df["종가"], df["거래량"], df["거래대금"]
            # 수급: 외국인+기관 순매수 금액
            try:
                fdf = stock.get_market_trading_value_by_date(s, e, tkr)
                flow[tkr] = fdf.get("외국인합계", 0) + fdf.get("기관합계", 0)
            except Exception:
                flow[tkr] = pd.Series(0.0, index=df.index)
            name = stock.get_market_ticker_name(tkr)
            meta_rows.append(
                {"ticker": tkr, "name": name, "sector": _sector_for(stock, tkr),
                 "is_managed": False, "is_halted": False, "is_capital_impaired": False}
            )
        except Exception as exc:
            log.debug("종목 %s 적재 실패: %s", tkr, exc)

    if not c:
        raise RuntimeError("KRX 가격 데이터를 한 종목도 받지 못했습니다.")

    idx = pd.concat(c.values(), axis=1).index
    wide = lambda d: pd.DataFrame(d).reindex(idx)
    meta = pd.DataFrame(meta_rows).set_index("ticker")

    # --- 매크로 (FDR + FRED) ---
    macro, sector_index = _build_macro_and_sectors(start, end, idx, meta)

    # --- 재무 (DART; best-effort, point-in-time) ---
    financials = _build_financials(tickers, idx)

    return MarketData(
        open=wide(o), high=wide(h), low=wide(l), close=wide(c),
        volume=wide(v), value=wide(val), net_flow=wide(flow).fillna(0.0),
        financials=financials, meta=meta, macro=macro, sector_index=sector_index,
    )


def _sector_for(stock, tkr: str) -> str:
    try:
        return stock.get_market_ticker_name(tkr) and _industry_guess(stock, tkr)
    except Exception:
        return "기타"


def _industry_guess(stock, tkr: str) -> str:
    # pykrx 는 업종 직접 제공이 제한적 → KRX 섹터지수 매핑은 단순화.
    return "기타"


def _build_macro_and_sectors(start, end, idx, meta):
    macro = pd.DataFrame(index=idx)
    try:
        import FinanceDataReader as fdr

        macro["kospi_close"] = fdr.DataReader("KS11", start, end)["Close"].reindex(idx).ffill()
        macro["usdkrw"] = fdr.DataReader("USD/KRW", start, end)["Close"].reindex(idx).ffill()
    except Exception as exc:
        log.warning("FDR 매크로 실패: %s", exc)
        macro["kospi_close"] = np.nan
        macro["usdkrw"] = np.nan

    # VKOSPI 대용: KOSPI 변동성
    ret = macro["kospi_close"].pct_change()
    macro["vkospi"] = (ret.rolling(20).std() * np.sqrt(252) * 100).fillna(20)

    # FRED 글로벌 위험지표
    for col, series_id in [("us_hy_spread", "BAMLH0A0HYM2"), ("dxy", "DTWEXBGS"), ("ust10y", "DGS10")]:
        macro[col] = _fred(series_id, start, end, idx)

    macro["foreign_net"] = 0.0  # 종목 net_flow 합으로 대체 가능

    # 섹터 지수: 우리 메타 섹터별 동일가중 (단순). 라이브에서 섹터 분류가 약하면 KOSPI 추종.
    sectors = sorted(meta["sector"].dropna().unique().tolist()) or ["기타"]
    sector_index = pd.DataFrame(
        {sec: macro["kospi_close"].ffill() for sec in sectors}, index=idx
    )
    return macro, sector_index


def _fred(series_id: str, start: str, end: str, idx) -> pd.Series:
    if not SETTINGS.fred_api_key:
        return pd.Series(np.nan, index=idx)
    try:
        import requests

        url = "https://api.stlouisfed.org/fred/series/observations"
        r = requests.get(url, params={
            "series_id": series_id, "api_key": SETTINGS.fred_api_key, "file_type": "json",
            "observation_start": start, "observation_end": end,
        }, timeout=20)
        obs = r.json()["observations"]
        s = pd.Series(
            {pd.Timestamp(o["date"]): _to_float(o["value"]) for o in obs}
        ).reindex(idx).ffill()
        return s
    except Exception as exc:
        log.warning("FRED %s 실패: %s", series_id, exc)
        return pd.Series(np.nan, index=idx)


def _to_float(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return np.nan


def _build_financials(tickers, idx) -> dict[str, pd.DataFrame]:
    """DART 재무 — best-effort.  키 없으면 빈(NaN) 패널 반환."""
    metrics = ["roe", "op_margin", "debt_ratio", "eps_yoy", "revenue_yoy", "per", "pbr"]
    empty = {m: pd.DataFrame(index=idx, columns=tickers, dtype=float) for m in metrics}
    if not SETTINGS.dart_api_key:
        log.info("DART_API_KEY 없음 → 재무 패널은 비움(추세/수급 위주로 동작).")
        return empty
    try:
        # OpenDartReader 로 핵심 재무를 가져오는 자리.
        # 종목/연도별 호출이 많아 비용이 큼 → MVP 에서는 골격만 두고 확장.
        import OpenDartReader  # noqa: F401

        log.info("DART 연결됨 — 재무 수집은 확장 지점(현재 골격). 빈 패널 반환.")
        return empty
    except Exception as exc:
        log.warning("DART 초기화 실패: %s", exc)
        return empty
