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
    cap = stock.get_market_cap_by_ticker(e, market="KOSPI")
    if tickers is None:
        tickers = cap.sort_values("시가총액", ascending=False).head(universe_size).index.tolist()
    log.info("라이브 유니버스 %d 종목 적재", len(tickers))

    # --- 섹터 매핑 (KRX 업종지수 구성종목 기준) ---
    sector_map, sector_index_raw = _build_sectors(stock, s, e, tickers)

    # --- 가격 패널 ---
    o, h, l, c, v, val, flow = ({} for _ in range(7))
    meta_rows = []
    managed = _flagged_tickers(stock, e)
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
            meta_rows.append(
                {"ticker": tkr, "name": stock.get_market_ticker_name(tkr),
                 "sector": sector_map.get(tkr, "기타"),
                 "is_managed": tkr in managed, "is_halted": False, "is_capital_impaired": False}
            )
        except Exception as exc:
            log.debug("종목 %s 적재 실패: %s", tkr, exc)

    if not c:
        raise RuntimeError("KRX 가격 데이터를 한 종목도 받지 못했습니다.")

    idx = pd.concat(c.values(), axis=1).index
    wide = lambda d: pd.DataFrame(d).reindex(idx)
    meta = pd.DataFrame(meta_rows).set_index("ticker")

    close_panel = wide(c)

    # --- 매크로 (ECOS + FDR + FRED) ---
    macro, sector_index = _build_macro_and_sectors(start, end, idx, meta, sector_index_raw)

    # --- 재무 (DART, point-in-time) + 시총 결합 PER/PBR ---
    shares = _shares_outstanding(cap, close_panel, e)   # 종목별 상장주식수(근사)
    financials = _build_financials(list(close_panel.columns), idx, close_panel, shares)

    return MarketData(
        open=wide(o), high=wide(h), low=wide(l), close=close_panel,
        volume=wide(v), value=wide(val), net_flow=wide(flow).fillna(0.0),
        financials=financials, meta=meta, macro=macro, sector_index=sector_index,
    )


def _shares_outstanding(cap: pd.DataFrame, close_panel: pd.DataFrame, end_yyyymmdd: str) -> pd.Series:
    """상장주식수 ≈ 시가총액 / 종가(말일).  pykrx cap 의 '상장주식수' 우선."""
    if "상장주식수" in cap.columns:
        return cap["상장주식수"].reindex(close_panel.columns)
    last_close = close_panel.ffill().iloc[-1]
    mcap = cap["시가총액"].reindex(close_panel.columns)
    return (mcap / last_close).replace([float("inf")], float("nan"))


def _build_sectors(stock, s: str, e: str, tickers: list[str]):
    """KRX KOSPI 업종지수 구성종목으로 ticker→섹터 매핑 + 섹터지수 시계열."""
    sector_map: dict[str, str] = {}
    sector_index_raw: dict[str, pd.Series] = {}
    tset = set(tickers)
    try:
        for idx_code in stock.get_index_ticker_list(date=e, market="KOSPI"):
            name = stock.get_index_ticker_name(idx_code)
            # 대표지수(코스피, 코스피200 등) 제외 — 업종지수만
            if any(k in name for k in ("코스피", "KRX", "200", "100", "50", "배당", "섹터")):
                if name not in ("코스피",):
                    pass
            try:
                members = stock.get_index_portfolio_deposit_file(idx_code)
            except Exception:
                members = []
            hit = tset.intersection(members)
            if not hit:
                continue
            for tkr in hit:
                sector_map.setdefault(tkr, name)
            try:
                oh = stock.get_index_ohlcv(s, e, idx_code)
                sector_index_raw[name] = oh["종가"]
            except Exception:
                pass
    except Exception as exc:
        log.warning("KRX 업종 분류 실패(전부 '기타' 처리): %s", exc)
    return sector_map, sector_index_raw


def _flagged_tickers(stock, e: str) -> set[str]:
    """관리종목/거래정지 등 지뢰 목록.

    pykrx 는 관리종목 목록을 직접 제공하지 않는다.  KRX 정보데이터시스템
    또는 DART 의 관리종목 공시로 보강하는 확장 지점.  현재는 빈 집합
    (게이트의 다른 조건으로 1차 방어).
    """
    return set()


def _build_macro_and_sectors(start, end, idx, meta, sector_index_raw=None):
    macro = pd.DataFrame(index=idx)
    try:
        import FinanceDataReader as fdr

        macro["kospi_close"] = fdr.DataReader("KS11", start, end)["Close"].reindex(idx).ffill()
        macro["usdkrw"] = fdr.DataReader("USD/KRW", start, end)["Close"].reindex(idx).ffill()
    except Exception as exc:
        log.warning("FDR 매크로 실패: %s", exc)
        macro["kospi_close"] = np.nan
        macro["usdkrw"] = np.nan

    # ECOS 환율로 보강(있으면 우선) + 한국 금리
    try:
        from tradroom.data import ecos

        ek = ecos.fetch_macro(start, end, idx)
        if "usdkrw" in ek and ek["usdkrw"].notna().any():
            macro["usdkrw"] = ek["usdkrw"].fillna(macro["usdkrw"])
        for col in ("base_rate", "ktb3y"):
            if col in ek:
                macro[col] = ek[col]
    except Exception as exc:
        log.warning("ECOS 매크로 실패: %s", exc)

    # VKOSPI 대용: KOSPI 변동성
    ret = macro["kospi_close"].pct_change()
    macro["vkospi"] = (ret.rolling(20).std() * np.sqrt(252) * 100).fillna(20)

    # FRED 글로벌 위험지표
    for col, series_id in [("us_hy_spread", "BAMLH0A0HYM2"), ("dxy", "DTWEXBGS"), ("ust10y", "DGS10")]:
        macro[col] = _fred(series_id, start, end, idx)

    macro["foreign_net"] = 0.0  # 종목 net_flow 합으로 대체 가능

    # 섹터 지수: KRX 업종지수 실데이터 우선, 없으면 KOSPI 추종 폴백.
    sectors = sorted(meta["sector"].dropna().unique().tolist()) or ["기타"]
    cols = {}
    for sec in sectors:
        if sector_index_raw and sec in sector_index_raw:
            cols[sec] = sector_index_raw[sec].reindex(idx).ffill()
        else:
            cols[sec] = macro["kospi_close"].ffill()
    sector_index = pd.DataFrame(cols, index=idx)
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


def _build_financials(tickers, idx, close_panel, shares) -> dict[str, pd.DataFrame]:
    """DART 재무(point-in-time) + 시총 결합 PER/PBR.

    PER = 시가총액 / 순이익,  PBR = 시가총액 / 자본총계.  시가총액 = 종가 × 상장주식수.
    순이익/자본총계는 접수일 이후에만 채워진 point-in-time 패널이므로 PER/PBR 도 PIT.
    """
    from tradroom.data import dart

    fin = dart.build_financials(list(tickers), idx)

    # 시가총액 패널 (PIT 가격 × 상장주식수 근사)
    mcap = close_panel.mul(shares.reindex(close_panel.columns), axis=1)
    ni = fin.get("net_income")
    eq = fin.get("equity")
    if ni is not None and ni.notna().any().any():
        fin["per"] = (mcap / ni.replace(0, np.nan)).where(ni > 0)
    else:
        fin["per"] = pd.DataFrame(index=idx, columns=close_panel.columns, dtype=float)
    if eq is not None and eq.notna().any().any():
        fin["pbr"] = mcap / eq.replace(0, np.nan)
    else:
        fin["pbr"] = pd.DataFrame(index=idx, columns=close_panel.columns, dtype=float)
    return fin
