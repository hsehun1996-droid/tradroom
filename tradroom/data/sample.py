"""합성 샘플 데이터 생성기.

API 키 없이도 전체 파이프라인(팩터→스코어→백테스트→추천→대시보드)이
end-to-end 동작하도록 *현실적인* 가짜 시장을 만든다.  결정론적(seed 고정).

모델: 시장 레짐 사이클(불/곰) + 섹터 모멘텀 + 종목별 GBM + 수급/재무/매크로.
실제 데이터로 바꿔도 동일한 MarketData 인터페이스이므로 코드 변경 불필요.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from tradroom.data.base import MarketData

_SECTORS = ["반도체", "2차전지", "바이오", "인터넷", "자동차", "금융"]
_NAMES = {
    "반도체": ["삼전자", "하닉스", "DB하이", "원익IPS", "리노공업", "티씨케이"],
    "2차전지": ["엘지엔솔", "에코프로", "포스퓨", "엘앤에프", "성우하이텍"],
    "바이오": ["셀트리온", "삼바", "유한양행", "한미약품", "알테오젠"],
    "인터넷": ["네이버", "카카오", "더존비즈", "NHN"],
    "자동차": ["현대차", "기아", "현대모비스", "한온시스템"],
    "금융": ["KB금융", "신한지주", "하나금융", "메리츠", "삼성생명"],
}


def generate_sample(
    start: str = "2021-01-01",
    end: str = "2024-12-31",
    seed: int = 7,
) -> MarketData:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start, end)
    n = len(dates)

    # --- 1. 시장 레짐 사이클 (장기 사인 + 노이즈) ---
    t = np.arange(n)
    market_drift = 0.0003 + 0.0006 * np.sin(2 * np.pi * t / 320)  # 불/곰 사이클
    market_vol = 0.010 + 0.006 * (1 - np.cos(2 * np.pi * t / 280)) / 2
    market_ret = rng.normal(market_drift, market_vol)
    kospi = 2400 * np.exp(np.cumsum(market_ret))

    # VKOSPI: 변동성에 연동 (시장 급락 시 급등)
    down = np.clip(-market_ret, 0, None)
    vkospi = 15 + 600 * pd.Series(down).rolling(5).mean().fillna(0).to_numpy() + rng.normal(0, 1.5, n)
    vkospi = np.clip(vkospi, 10, 60)

    # 매크로
    usdkrw = 1150 * np.exp(np.cumsum(rng.normal(0.0001 - 0.5 * market_drift, 0.004)))
    us_hy_spread = np.clip(3.5 - 200 * (market_drift - 0.0003) + rng.normal(0, 0.2, n), 2.5, 9.0)
    dxy = 95 * np.exp(np.cumsum(rng.normal(0.0, 0.003, n)))
    ust10y = np.clip(2.0 + np.cumsum(rng.normal(0.0005, 0.02, n)) * 0.01, 0.5, 5.0)
    foreign_net = rng.normal(market_ret * 5e12, 3e11)  # 시장과 동행하는 외국인 순매수

    # --- 2. 섹터 모멘텀 (섹터마다 다른 추세 사이클) ---
    sector_ret = {}
    for i, s in enumerate(_SECTORS):
        phase = 2 * np.pi * (i / len(_SECTORS))
        drift = 0.0002 + 0.0010 * np.sin(2 * np.pi * t / (260 + 40 * i) + phase)
        sector_ret[s] = 0.5 * market_ret + 0.5 * rng.normal(drift, 0.012)
    sector_index = pd.DataFrame(
        {s: 1000 * np.exp(np.cumsum(r)) for s, r in sector_ret.items()}, index=dates
    )

    # --- 3. 종목 ---
    tickers, meta_rows = [], []
    open_, high_, low_, close_, vol_, val_, flow_ = ({} for _ in range(7))
    fin_roe, fin_opm, fin_debt, fin_eps_yoy, fin_rev_yoy, fin_per, fin_pbr = ({} for _ in range(7))

    code = 100
    for s in _SECTORS:
        for name in _NAMES[s]:
            code += 5
            tkr = f"{code:06d}"
            tickers.append(tkr)
            beta_sector = rng.uniform(0.7, 1.3)
            idio_drift = rng.normal(0.0, 0.0004)
            idio_vol = rng.uniform(0.014, 0.028)
            ret = beta_sector * sector_ret[s] + rng.normal(idio_drift, idio_vol, n)
            price = rng.uniform(8000, 90000) * np.exp(np.cumsum(ret))
            c = pd.Series(price, index=dates)
            intraday = np.abs(rng.normal(0, 0.012, n))
            o = c.shift(1).fillna(c.iloc[0]) * (1 + rng.normal(0, 0.004, n))
            h = np.maximum(o, c) * (1 + intraday)
            lo = np.minimum(o, c) * (1 - intraday)
            base_shares = rng.uniform(2e6, 4e7)
            v = (base_shares * (1 + 0.5 * np.abs(ret) / idio_vol)).round()
            value = c * v

            close_[tkr], open_[tkr], high_[tkr], low_[tkr] = c, o, pd.Series(h, index=dates), pd.Series(lo, index=dates)
            vol_[tkr], val_[tkr] = pd.Series(v, index=dates), value
            # 수급: 종목 수익률 + 섹터 수급에 연동
            flow_[tkr] = pd.Series(rng.normal(ret * value.mean() * 0.05, value.mean() * 0.01), index=dates)

            # 재무 (분기마다 갱신, point-in-time: 접수일 이후만 채움)
            roe = np.clip(rng.normal(0.10, 0.06), -0.1, 0.35)
            opm = np.clip(rng.normal(0.10, 0.07), -0.15, 0.4)
            debt = np.clip(rng.normal(0.8, 0.4), 0.05, 3.0)
            eps_yoy = rng.normal(0.08, 0.25)
            rev_yoy = rng.normal(0.07, 0.18)
            per = np.clip(rng.normal(15, 8), 3, 60)
            pbr = np.clip(rng.normal(1.5, 0.9), 0.3, 8)
            fin_roe[tkr] = _quarterly_pit(dates, roe, rng)
            fin_opm[tkr] = _quarterly_pit(dates, opm, rng)
            fin_debt[tkr] = _quarterly_pit(dates, debt, rng, drift=-0.02)
            fin_eps_yoy[tkr] = _quarterly_pit(dates, eps_yoy, rng, vol=0.05)
            fin_rev_yoy[tkr] = _quarterly_pit(dates, rev_yoy, rng, vol=0.03)
            fin_per[tkr] = _quarterly_pit(dates, per, rng, vol=1.0)
            fin_pbr[tkr] = _quarterly_pit(dates, pbr, rng, vol=0.1)

            meta_rows.append(
                {
                    "ticker": tkr,
                    "name": name,
                    "sector": s,
                    "is_managed": False,
                    "is_halted": False,
                    "is_capital_impaired": rng.random() < 0.03,
                }
            )

    def wide(d: dict) -> pd.DataFrame:
        return pd.DataFrame(d)[tickers]

    meta = pd.DataFrame(meta_rows).set_index("ticker")
    macro = pd.DataFrame(
        {
            "kospi_close": kospi,
            "vkospi": vkospi,
            "usdkrw": usdkrw,
            "us_hy_spread": us_hy_spread,
            "dxy": dxy,
            "ust10y": ust10y,
            "foreign_net": foreign_net,
        },
        index=dates,
    )

    return MarketData(
        open=wide(open_),
        high=wide(high_),
        low=wide(low_),
        close=wide(close_),
        volume=wide(vol_),
        value=wide(val_),
        net_flow=wide(flow_),
        financials={
            "roe": wide(fin_roe),
            "op_margin": wide(fin_opm),
            "debt_ratio": wide(fin_debt),
            "eps_yoy": wide(fin_eps_yoy),
            "revenue_yoy": wide(fin_rev_yoy),
            "per": wide(fin_per),
            "pbr": wide(fin_pbr),
        },
        meta=meta,
        macro=macro,
        sector_index=sector_index,
    )


def _quarterly_pit(
    dates: pd.DatetimeIndex, base: float, rng, drift: float = 0.0, vol: float = 0.0
) -> pd.Series:
    """분기마다 값이 갱신되는 point-in-time 재무 시계열.

    각 분기 값은 *접수일(다음 분기 시작 무렵)* 이후에만 보이도록 forward-fill.
    """
    s = pd.Series(np.nan, index=dates)
    quarters = pd.date_range(dates[0], dates[-1], freq="QS")
    val = base
    for q in quarters:
        # 접수일 = 분기말 + 약 45일 (공시 시차)
        announce = q + pd.Timedelta(days=45)
        val = val * (1 + drift) + rng.normal(0, vol)
        s.loc[s.index >= announce] = val
    return s.ffill().bfill()
