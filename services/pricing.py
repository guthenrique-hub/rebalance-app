from __future__ import annotations

from typing import Iterable

import pandas as pd
import streamlit as st
import yfinance as yf


def normalize_brazilian_ticker(ticker: str) -> str:
    clean = str(ticker).strip().upper()
    if not clean:
        return clean
    return clean if clean.endswith(".SA") else f"{clean}.SA"


def _safe_float(value) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        value = float(value)
        return value if value > 0 else None
    except (TypeError, ValueError):
        return None


@st.cache_data(ttl=300, show_spinner=False)
def get_yfinance_price(ticker: str) -> float | None:
    yf_ticker = normalize_brazilian_ticker(ticker)
    asset = yf.Ticker(yf_ticker)

    try:
        info = asset.get_info()
    except Exception:
        info = {}

    for field in ("regularMarketPrice", "currentPrice", "previousClose"):
        price = _safe_float(info.get(field))
        if price:
            return price

    try:
        fast_info = asset.fast_info
        price = _safe_float(fast_info.get("last_price"))
        if price:
            return price
    except Exception:
        pass

    try:
        history = asset.history(period="5d")
        if not history.empty:
            close = history["Close"].dropna()
            if not close.empty:
                return _safe_float(close.iloc[-1])
    except Exception:
        pass

    return None


def fetch_prices(tickers: Iterable[str]) -> pd.DataFrame:
    rows = []
    for ticker in sorted({str(t).strip().upper() for t in tickers if str(t).strip()}):
        price = get_yfinance_price(ticker)
        rows.append(
            {
                "ticker": ticker,
                "ticker_yfinance": normalize_brazilian_ticker(ticker),
                "preco": price,
                "status": "OK" if price else "PENDENTE",
            }
        )
    return pd.DataFrame(rows, columns=["ticker", "ticker_yfinance", "preco", "status"])
