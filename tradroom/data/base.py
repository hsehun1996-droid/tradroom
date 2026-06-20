"""표준 데이터 컨테이너.

모든 시계열은 **wide 패널**(index=날짜, columns=종목코드)으로 보관해
팩터 계산을 벡터화한다.  재무/밸류 패널은 이미 point-in-time으로
forward-fill 되어 있다고 가정한다(공시 접수일 이후에만 값이 채워짐).
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class MarketData:
    """시스템 전체가 소비하는 단일 데이터 묶음."""

    # --- 가격 패널 (index=date, columns=ticker) ---
    open: pd.DataFrame
    high: pd.DataFrame
    low: pd.DataFrame
    close: pd.DataFrame
    volume: pd.DataFrame
    value: pd.DataFrame            # 거래대금 (원)

    # --- 수급: 외국인+기관 순매수 금액 (index=date, columns=ticker) ---
    net_flow: pd.DataFrame

    # --- 재무/밸류 패널 (point-in-time forward-filled, index=date, columns=ticker) ---
    financials: dict[str, pd.DataFrame]   # ex: {"roe": df, "per": df, ...}

    # --- 메타 (index=ticker) ---
    meta: pd.DataFrame             # name, sector, is_managed, is_halted, is_capital_impaired

    # --- 매크로 (index=date) ---
    macro: pd.DataFrame            # kospi_close, vkospi, usdkrw, us_hy_spread, dxy, ust10y, foreign_net

    # --- 섹터 지수 (index=date, columns=sector) ---
    sector_index: pd.DataFrame

    @property
    def tickers(self) -> list[str]:
        return list(self.close.columns)

    @property
    def dates(self) -> pd.DatetimeIndex:
        return self.close.index

    @property
    def sectors(self) -> list[str]:
        return sorted(self.meta["sector"].dropna().unique().tolist())

    def sector_of(self, ticker: str) -> str:
        return self.meta.loc[ticker, "sector"]

    def fin(self, metric: str) -> pd.DataFrame:
        """재무 패널 조회. 없으면 NaN 패널 반환(팩터가 우아하게 무시)."""
        if metric in self.financials:
            return self.financials[metric]
        return pd.DataFrame(index=self.close.index, columns=self.close.columns, dtype=float)

    def slice_until(self, date: pd.Timestamp) -> "MarketData":
        """date 까지의 데이터만 잘라 반환 — look-ahead 방지용."""

        def cut(df: pd.DataFrame) -> pd.DataFrame:
            return df.loc[df.index <= date]

        return MarketData(
            open=cut(self.open),
            high=cut(self.high),
            low=cut(self.low),
            close=cut(self.close),
            volume=cut(self.volume),
            value=cut(self.value),
            net_flow=cut(self.net_flow),
            financials={k: cut(v) for k, v in self.financials.items()},
            meta=self.meta,
            macro=cut(self.macro),
            sector_index=cut(self.sector_index),
        )
