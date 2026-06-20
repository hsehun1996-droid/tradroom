"""ECOS (한국은행 경제통계) 어댑터.

REST 규격:
  GET https://ecos.bok.or.kr/api/StatisticSearch/{KEY}/json/kr/{s}/{e}/
      {STAT_CODE}/{CYCLE}/{START}/{END}/{ITEM1}
  정상: {"StatisticSearch": {"list_total_count": N, "row": [{TIME, DATA_VALUE, ...}]}}
  오류: {"RESULT": {"CODE": "...", "MESSAGE": "..."}}

주의: 통계코드(STAT_CODE)/항목코드(ITEM_CODE)는 ECOS '통계코드검색'에서
바뀔 수 있습니다.  아래 기본값은 작성 시점 기준 — 실행 전 재확인 권장.
각 호출은 실패 시 빈 Series 로 우아하게 강등됩니다(시스템 무중단).
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from tradroom.config import SETTINGS

log = logging.getLogger(__name__)

_BASE = "https://ecos.bok.or.kr/api/StatisticSearch"

# (STAT_CODE, ITEM_CODE, CYCLE) — 실행 전 ECOS 에서 코드 재확인 권장
DEFAULTS = {
    "usdkrw": ("731Y001", "0000001", "D"),   # 원/달러 환율(매매기준율)
    "base_rate": ("722Y001", "0101000", "D"), # 한국은행 기준금리
    "ktb3y": ("817Y002", "010200000", "D"),   # 국고채(3년)
}


def fetch_series(
    stat_code: str, item_code: str, cycle: str, start: str, end: str
) -> pd.Series:
    """ECOS 단일 통계 시계열 → DatetimeIndex Series."""
    if not SETTINGS.ecos_api_key:
        return pd.Series(dtype=float)
    import requests

    s, e = _fmt(start, cycle), _fmt(end, cycle)
    url = f"{_BASE}/{SETTINGS.ecos_api_key}/json/kr/1/100000/{stat_code}/{cycle}/{s}/{e}/{item_code}"
    try:
        r = requests.get(url, timeout=30)
        j = r.json()
        if "RESULT" in j:  # 오류 응답
            log.warning("ECOS %s 오류: %s", stat_code, j["RESULT"])
            return pd.Series(dtype=float)
        rows = j.get("StatisticSearch", {}).get("row", [])
        if not rows:
            return pd.Series(dtype=float)
        idx = [_parse_time(x["TIME"], cycle) for x in rows]
        vals = [_to_float(x.get("DATA_VALUE")) for x in rows]
        return pd.Series(vals, index=pd.DatetimeIndex(idx)).sort_index()
    except Exception as exc:
        log.warning("ECOS %s 요청 실패: %s", stat_code, exc)
        return pd.Series(dtype=float)


def fetch_usdkrw(start: str, end: str) -> pd.Series:
    return fetch_series(*DEFAULTS["usdkrw"], start, end)


def fetch_macro(start: str, end: str, index: pd.DatetimeIndex) -> pd.DataFrame:
    """레짐에 쓰는 한국 매크로 묶음(환율·기준금리·국고채). 결측은 ffill."""
    out = pd.DataFrame(index=index)
    for name, (sc, ic, cy) in DEFAULTS.items():
        s = fetch_series(sc, ic, cy, start, end)
        out[name] = s.reindex(index, method="ffill") if not s.empty else np.nan
    return out


def _fmt(date: str, cycle: str) -> str:
    d = pd.Timestamp(date)
    return {"D": d.strftime("%Y%m%d"), "M": d.strftime("%Y%m"),
            "Q": f"{d.year}Q{d.quarter}", "A": d.strftime("%Y")}.get(cycle, d.strftime("%Y%m%d"))


def _parse_time(t: str, cycle: str) -> pd.Timestamp:
    if cycle == "D":
        return pd.Timestamp(t)
    if cycle == "M":
        return pd.Timestamp(f"{t[:4]}-{t[4:6]}-01")
    if cycle == "Q":
        y, q = t[:4], int(t[-1])
        return pd.Timestamp(f"{y}-{(q-1)*3+1:02d}-01")
    return pd.Timestamp(f"{t[:4]}-01-01")


def _to_float(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return np.nan
