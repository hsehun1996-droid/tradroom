"""라이브 데이터 연결·키 유효성 진단.

허용목록(egress)에 호스트를 추가한 뒤 실행하면 각 소스의 도달 가능성과
키 유효성을 한 번에 점검한다.  키는 .env 에서 읽는다(코드/깃에 넣지 않음).

사용:  PYTHONPATH=. python scripts/check_live.py
"""
from __future__ import annotations

import sys

from tradroom.config import SETTINGS


def _ok(msg):
    print(f"  ✅ {msg}")


def _fail(msg):
    print(f"  ❌ {msg}")


def check_fred():
    print("FRED (api.stlouisfed.org)")
    if not SETTINGS.fred_api_key:
        return _fail("FRED_API_KEY 없음")
    import requests

    try:
        r = requests.get(
            "https://api.stlouisfed.org/fred/series/observations",
            params={"series_id": "DGS10", "api_key": SETTINGS.fred_api_key,
                    "file_type": "json", "limit": 1, "sort_order": "desc"},
            timeout=20,
        )
        if r.status_code == 200 and r.json().get("observations"):
            _ok(f"최신 미 10년물 = {r.json()['observations'][0]['value']}")
        else:
            _fail(f"status {r.status_code}: {r.text[:120]}")
    except Exception as exc:
        _fail(str(exc)[:120])


def check_dart():
    print("DART (opendart.fss.or.kr)")
    if not SETTINGS.dart_api_key:
        return _fail("DART_API_KEY 없음")
    import requests

    try:
        r = requests.get("https://opendart.fss.or.kr/api/list.json",
                         params={"crtfc_key": SETTINGS.dart_api_key,
                                 "bgn_de": "20240102", "end_de": "20240105", "page_count": 5},
                         timeout=20)
        j = r.json()
        if j.get("status") == "000":
            _ok(f"공시 {len(j.get('list', []))}건 조회 (status 000)")
        else:
            _fail(f"status {j.get('status')}: {j.get('message')}")
    except Exception as exc:
        _fail(str(exc)[:120])


def check_ecos():
    print("ECOS (ecos.bok.or.kr)")
    if not SETTINGS.ecos_api_key:
        return _fail("ECOS_API_KEY 없음")
    from tradroom.data import ecos

    s = ecos.fetch_usdkrw("2024-01-02", "2024-01-10")
    if not s.empty:
        _ok(f"원/달러 {len(s)}일 조회, 최근 {s.iloc[-1]:.1f}")
    else:
        _fail("데이터 없음 (키/통계코드 확인 — DEFAULTS 의 STAT_CODE 재확인)")


def check_krx():
    print("KRX / pykrx (data.krx.co.kr)")
    try:
        from pykrx import stock

        df = stock.get_market_ohlcv("20240102", "20240110", "005930")
        if not df.empty:
            _ok(f"삼성전자 {len(df)}일 시세, 최근 종가 {df['종가'].iloc[-1]:,.0f}")
        else:
            _fail("데이터 없음")
    except ImportError:
        _fail("pykrx 미설치 (pip install pykrx)")
    except Exception as exc:
        _fail(str(exc)[:120])


def check_kis():
    print("KIS (openapi.koreainvestment.com:9443)")
    if not (SETTINGS_has("KIS_APP_KEY") and SETTINGS_has("KIS_APP_SECRET")):
        return _fail("KIS_APP_KEY / KIS_APP_SECRET 없음")
    try:
        from tradroom.data.kis import KISClient

        c = KISClient()
        tok = c.token()
        _ok(f"토큰 발급 OK (…{tok[-6:]})")
        px = c.current_price("005930")
        _ok(f"삼성전자 현재가 {px['price']:,.0f} (PER {px['per']}, PBR {px['pbr']})")
    except Exception as exc:
        _fail(str(exc)[:160])


def SETTINGS_has(name: str) -> bool:
    import os

    return bool(os.getenv(name, ""))


def main():
    print("=" * 56)
    print("라이브 데이터 연결 진단  (키는 .env 에서 로드)")
    print("=" * 56)
    for fn in (check_krx, check_dart, check_ecos, check_fred, check_kis):
        fn()
        print()
    print("차단(403 Host not in allowlist)이 보이면 환경 egress 허용목록에 호스트를 추가하세요.")


if __name__ == "__main__":
    sys.exit(main())
