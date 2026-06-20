"""DART (전자공시) 재무 어댑터 — OpenDartReader 기반.

핵심 원칙(블루프린트 3.2): **point-in-time**.  각 재무 수치는 *공시 접수일
(rcept_dt)* 이후에만 보이도록 forward-fill 한다.  2023 사업보고서를 2024년 3월에
알았던 것처럼 처리해 look-ahead 를 차단한다.

산출 패널(index=date, columns=ticker):
  raw    : net_income, equity, liabilities, revenue, op_income
  derived: roe, op_margin, debt_ratio, eps_yoy, revenue_yoy

PER/PBR 은 시가총액이 필요하므로 live.py 에서 시총과 결합해 계산한다.

주의: 여기서 live 검증은 불가(환경 egress 차단).  실행은 허용목록 추가 후
또는 로컬에서.  계정 매칭은 account_id(IFRS 태그) 우선, 없으면 account_nm.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from tradroom.config import SETTINGS

log = logging.getLogger(__name__)

# IFRS account_id 우선, 폴백으로 계정명 부분일치
_ACCOUNTS = {
    "revenue": (["ifrs-full_Revenue", "ifrs_Revenue"], ["매출액", "수익(매출액)", "영업수익"]),
    "op_income": (["dart_OperatingIncomeLoss", "ifrs-full_OperatingIncomeLoss"], ["영업이익"]),
    "net_income": (["ifrs-full_ProfitLoss", "ifrs_ProfitLoss"], ["당기순이익", "당기순이익(손실)"]),
    "equity": (["ifrs-full_Equity", "ifrs_Equity"], ["자본총계"]),
    "liabilities": (["ifrs-full_Liabilities", "ifrs_Liabilities"], ["부채총계"]),
}
_RAW = list(_ACCOUNTS.keys())
_DERIVED = ["roe", "op_margin", "debt_ratio", "eps_yoy", "revenue_yoy"]


def build_financials(
    tickers: list[str],
    index: pd.DatetimeIndex,
    years: list[int] | None = None,
    reprt_code: str = "11011",   # 11011 사업보고서(연간)
) -> dict[str, pd.DataFrame]:
    """DART 재무 → point-in-time 패널 dict.  키 없으면 빈 패널."""
    empty = {m: pd.DataFrame(index=index, columns=tickers, dtype=float) for m in _RAW + _DERIVED}
    if not SETTINGS.dart_api_key:
        log.info("DART_API_KEY 없음 → 재무 패널 비움(추세/수급 위주 동작).")
        return empty
    try:
        import OpenDartReader
    except ImportError:
        log.warning("OpenDartReader 미설치 → 재무 패널 비움.  pip install OpenDartReader")
        return empty

    dart = OpenDartReader(SETTINGS.dart_api_key)
    years = years or sorted({index[0].year - 1, *range(index[0].year, index[-1].year + 1)})

    # ticker -> {rcept_date: {account: value}} (연도별 한 행)
    records: dict[str, list[dict]] = {}
    for tkr in tickers:
        rows = []
        for y in years:
            try:
                fs = dart.finstate_all(tkr, y, reprt_code=reprt_code)
            except Exception as exc:
                log.debug("DART %s %d 실패: %s", tkr, y, exc)
                continue
            if fs is None or len(fs) == 0:
                continue
            rows.append(_extract_year(fs, y))
        if rows:
            records[tkr] = [r for r in rows if r]

    return _to_panels(records, tickers, index)


def _extract_year(fs: pd.DataFrame, year: int) -> dict | None:
    """한 해 재무제표 DataFrame → {접수일, 계정값들, 전기값들}."""
    rcept_dt = _rcept_date(fs)
    out: dict = {"year": year, "rcept_dt": rcept_dt}
    for metric, (ids, names) in _ACCOUNTS.items():
        cur, prev = _pick_amount(fs, ids, names)
        out[metric] = cur
        out[f"{metric}_prev"] = prev
    # 핵심 값이 모두 결측이면 버림
    if all(pd.isna(out.get(m)) for m in _RAW):
        return None
    return out


def _rcept_date(fs: pd.DataFrame) -> pd.Timestamp:
    """접수일: rcept_dt 컬럼 우선, 없으면 rcept_no 앞 8자리(YYYYMMDD)."""
    if "rcept_dt" in fs.columns and fs["rcept_dt"].notna().any():
        return pd.Timestamp(str(fs["rcept_dt"].dropna().iloc[0]))
    if "rcept_no" in fs.columns and fs["rcept_no"].notna().any():
        rno = str(fs["rcept_no"].dropna().iloc[0])
        return pd.Timestamp(rno[:8])
    # 폴백: 연간보고서는 통상 다음 해 3월말 공시
    y = int(fs["bsns_year"].iloc[0]) if "bsns_year" in fs.columns else pd.Timestamp.now().year
    return pd.Timestamp(f"{y + 1}-03-31")


def _pick_amount(fs: pd.DataFrame, ids: list[str], names: list[str]) -> tuple[float, float]:
    """(당기금액, 전기금액).  account_id 우선, 폴백 account_nm 부분일치."""
    row = None
    if "account_id" in fs.columns:
        m = fs[fs["account_id"].isin(ids)]
        if len(m):
            row = m.iloc[0]
    if row is None and "account_nm" in fs.columns:
        for nm in names:
            m = fs[fs["account_nm"].astype(str).str.replace(" ", "").str.contains(nm.replace(" ", ""))]
            if len(m):
                row = m.iloc[0]
                break
    if row is None:
        return np.nan, np.nan
    return _amt(row.get("thstrm_amount")), _amt(row.get("frmtrm_amount"))


def _amt(x) -> float:
    try:
        return float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return np.nan


def _to_panels(records, tickers, index) -> dict[str, pd.DataFrame]:
    panels = {m: pd.DataFrame(index=index, columns=tickers, dtype=float) for m in _RAW + _DERIVED}
    for tkr, rows in records.items():
        rows = sorted(rows, key=lambda r: r["rcept_dt"])
        for r in rows:
            eff = r["rcept_dt"]
            ni, eq, li = r.get("net_income"), r.get("equity"), r.get("liabilities")
            rev, op = r.get("revenue"), r.get("op_income")
            derived = {
                "roe": _safe_div(ni, eq),
                "op_margin": _safe_div(op, rev),
                "debt_ratio": _safe_div(li, eq),
                "eps_yoy": _safe_div(ni - r.get("net_income_prev", np.nan), abs(r.get("net_income_prev", np.nan)))
                if pd.notna(r.get("net_income_prev")) else np.nan,
                "revenue_yoy": _safe_div(rev - r.get("revenue_prev", np.nan), abs(r.get("revenue_prev", np.nan)))
                if pd.notna(r.get("revenue_prev")) else np.nan,
            }
            mask = index >= eff
            for m in _RAW:
                panels[m].loc[mask, tkr] = r.get(m)
            for m, v in derived.items():
                panels[m].loc[mask, tkr] = v
    return panels


def _safe_div(a, b):
    try:
        if b in (0, None) or pd.isna(a) or pd.isna(b) or b == 0:
            return np.nan
        return a / b
    except TypeError:
        return np.nan
