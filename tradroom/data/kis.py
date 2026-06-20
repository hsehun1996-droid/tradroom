"""KIS (한국투자증권) Developers 어댑터 — 토큰 + 시세 조회 (읽기 전용).

블루프린트 3.1 1순위 소스.  OAuth2 client_credentials 로 액세스 토큰을 받고
국내주식 현재가/일별시세를 조회한다.  토큰은 발급 제한이 있어 파일 캐시
(유효 24h).  ★주문(매매) API 는 의도적으로 구현하지 않음 — 의사결정 지원 도구.★

주의: 실서버 도메인.  이 환경에서는 egress 차단으로 검증 불가 → 허용목록
추가(openapi.koreainvestment.com:9443) 후 또는 로컬에서 동작.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

from tradroom.config import SETTINGS

log = logging.getLogger(__name__)

_BASE = "https://openapi.koreainvestment.com:9443"
_TOKEN_CACHE = SETTINGS.data_dir / ".kis_token.json"


class KISClient:
    def __init__(self, app_key: str | None = None, app_secret: str | None = None):
        import os

        self.app_key = app_key or os.getenv("KIS_APP_KEY", "")
        self.app_secret = app_secret or os.getenv("KIS_APP_SECRET", "")
        if not (self.app_key and self.app_secret):
            raise RuntimeError("KIS_APP_KEY / KIS_APP_SECRET 가 필요합니다(.env).")
        self._token: str | None = None

    # --------------------------------------------------------------- token
    def _load_cached_token(self) -> str | None:
        try:
            if _TOKEN_CACHE.exists():
                d = json.loads(_TOKEN_CACHE.read_text())
                if d.get("app_key") == self.app_key and d.get("expire_ts", 0) > time.time() + 300:
                    return d["access_token"]
        except Exception:
            pass
        return None

    def token(self) -> str:
        if self._token:
            return self._token
        cached = self._load_cached_token()
        if cached:
            self._token = cached
            return cached

        import requests

        r = requests.post(
            f"{_BASE}/oauth2/tokenP",
            json={"grant_type": "client_credentials",
                  "appkey": self.app_key, "appsecret": self.app_secret},
            timeout=20,
        )
        r.raise_for_status()
        j = r.json()
        self._token = j["access_token"]
        expire_ts = time.time() + int(j.get("expires_in", 86400))
        try:
            _TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
            _TOKEN_CACHE.write_text(json.dumps(
                {"app_key": self.app_key, "access_token": self._token, "expire_ts": expire_ts}
            ))
            _TOKEN_CACHE.chmod(0o600)
        except Exception as exc:
            log.debug("토큰 캐시 저장 실패: %s", exc)
        return self._token

    def _headers(self, tr_id: str) -> dict:
        return {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self.token()}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
        }

    # --------------------------------------------------------------- quotes
    def current_price(self, ticker: str) -> dict:
        """국내주식 현재가 (FHKST01010100)."""
        import requests

        url = f"{_BASE}/uapi/domestic-stock/v1/quotations/inquire-price"
        params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": ticker}
        r = requests.get(url, headers=self._headers("FHKST01010100"), params=params, timeout=20)
        r.raise_for_status()
        out = r.json().get("output", {})
        return {
            "ticker": ticker,
            "price": _f(out.get("stck_prpr")),
            "change_pct": _f(out.get("prdy_ctrt")),
            "volume": _f(out.get("acml_vol")),
            "per": _f(out.get("per")),
            "pbr": _f(out.get("pbr")),
            "high52": _f(out.get("w52_hgpr")),
            "low52": _f(out.get("w52_lwpr")),
        }

    def daily_ohlcv(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        """일별 시세 (FHKST03010100).  index=date, OHLCV+거래대금."""
        import requests

        url = f"{_BASE}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
        params = {
            "FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": ticker,
            "FID_INPUT_DATE_1": start.replace("-", ""),
            "FID_INPUT_DATE_2": end.replace("-", ""),
            "FID_PERIOD_DIV_CODE": "D", "FID_ORG_ADJ_PRC": "0",
        }
        r = requests.get(url, headers=self._headers("FHKST03010100"), params=params, timeout=20)
        r.raise_for_status()
        rows = r.json().get("output2", []) or []
        recs = []
        for x in rows:
            if not x.get("stck_bsop_date"):
                continue
            recs.append({
                "date": pd.Timestamp(x["stck_bsop_date"]),
                "open": _f(x.get("stck_oprc")), "high": _f(x.get("stck_hgpr")),
                "low": _f(x.get("stck_lwpr")), "close": _f(x.get("stck_clpr")),
                "volume": _f(x.get("acml_vol")), "value": _f(x.get("acml_tr_pbmn")),
            })
        if not recs:
            return pd.DataFrame()
        return pd.DataFrame(recs).set_index("date").sort_index()


def _f(x):
    try:
        return float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return float("nan")
