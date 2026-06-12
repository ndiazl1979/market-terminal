#!/usr/bin/env python3
"""
fetch_data.py — Recolecta datos de mercado en vivo y los escribe en data.json.

Se ejecuta del lado servidor (GitHub Actions), por lo que NO hay restricciones de
CORS ni se necesita ninguna API key:
  - Acciones (AAPL, TSLA, NVDA): Yahoo Finance vía yfinance (precio + fundamentales
    + histórico diario de 1 año).
  - Cripto (BTC, ETH): CoinGecko API pública.

Para cada activo calcula indicadores técnicos (SMA50, SMA200, RSI-14) a partir del
histórico y deriva una señal compuesta COMPRA / MANTENER / VENTA.
"""

import json
import sys
import time
from datetime import datetime, timezone

import requests
import yfinance as yf

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) market-terminal/1.0"

STOCKS = [
    {"symbol": "AAPL", "name": "Apple Inc.", "logo": "AAPL"},
    {"symbol": "TSLA", "name": "Tesla, Inc.", "logo": "TSLA"},
    {"symbol": "NVDA", "name": "NVIDIA Corp.", "logo": "NVDA"},
]

CRYPTOS = [
    {"symbol": "BTC", "name": "Bitcoin", "cg_id": "bitcoin"},
    {"symbol": "ETH", "name": "Ethereum", "cg_id": "ethereum"},
]


# ---------------------------------------------------------------------------
# Indicadores técnicos
# ---------------------------------------------------------------------------
def sma(values, period):
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def rsi(values, period=14):
    """RSI de Wilder."""
    if len(values) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(values)):
        delta = values[i] - values[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def build_signal(price, sma50, sma200, rsi_val):
    """Combina varios criterios técnicos en una señal y un puntaje [-100, 100]."""
    score = 0
    reasons = []

    if sma50 is not None and price is not None:
        if price > sma50:
            score += 25
            reasons.append("Precio sobre SMA50 (tendencia corta alcista)")
        else:
            score -= 25
            reasons.append("Precio bajo SMA50 (tendencia corta bajista)")

    if sma200 is not None and price is not None:
        if price > sma200:
            score += 20
            reasons.append("Precio sobre SMA200 (tendencia larga alcista)")
        else:
            score -= 20
            reasons.append("Precio bajo SMA200 (tendencia larga bajista)")

    if sma50 is not None and sma200 is not None:
        if sma50 > sma200:
            score += 15
            reasons.append("Golden cross (SMA50 > SMA200)")
        else:
            score -= 15
            reasons.append("Death cross (SMA50 < SMA200)")

    if rsi_val is not None:
        if rsi_val < 30:
            score += 30
            reasons.append(f"RSI {rsi_val:.0f}: sobreventa")
        elif rsi_val > 70:
            score -= 30
            reasons.append(f"RSI {rsi_val:.0f}: sobrecompra")
        else:
            reasons.append(f"RSI {rsi_val:.0f}: neutral")

    if score >= 30:
        label = "COMPRA"
    elif score <= -30:
        label = "VENTA"
    else:
        label = "MANTENER"

    return label, score, reasons


def safe_round(v, n=2):
    try:
        return round(float(v), n)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Acciones
# ---------------------------------------------------------------------------
def fetch_stock(meta):
    sym = meta["symbol"]
    t = yf.Ticker(sym)
    info = t.info or {}
    hist = t.history(period="1y", interval="1d")
    closes = [float(x) for x in hist["Close"].dropna().tolist()]

    price = info.get("currentPrice") or info.get("regularMarketPrice")
    if price is None and closes:
        price = closes[-1]
    prev = info.get("regularMarketPreviousClose") or info.get("previousClose")
    if prev is None and len(closes) >= 2:
        prev = closes[-2]

    change = (price - prev) if (price is not None and prev is not None) else None
    change_pct = (change / prev * 100) if (change is not None and prev) else None

    s50 = sma(closes, 50)
    s200 = sma(closes, 200)
    r = rsi(closes, 14)
    signal, score, reasons = build_signal(price, s50, s200, r)

    return {
        "symbol": sym,
        "name": meta["name"],
        "type": "stock",
        "price": safe_round(price),
        "change": safe_round(change),
        "changePct": safe_round(change_pct),
        "open": safe_round(info.get("open") or info.get("regularMarketOpen")),
        "dayHigh": safe_round(info.get("dayHigh") or info.get("regularMarketDayHigh")),
        "dayLow": safe_round(info.get("dayLow") or info.get("regularMarketDayLow")),
        "week52High": safe_round(info.get("fiftyTwoWeekHigh")),
        "week52Low": safe_round(info.get("fiftyTwoWeekLow")),
        "volume": info.get("volume") or info.get("regularMarketVolume"),
        "marketCap": info.get("marketCap"),
        "pe": safe_round(info.get("trailingPE")),
        "forwardPe": safe_round(info.get("forwardPE")),
        "eps": safe_round(info.get("trailingEps")),
        "dividendYield": safe_round(info.get("dividendYield")),
        "beta": safe_round(info.get("beta")),
        "sma50": safe_round(s50),
        "sma200": safe_round(s200),
        "rsi": safe_round(r, 1),
        "signal": signal,
        "signalScore": score,
        "signalReasons": reasons,
        "spark": [safe_round(c) for c in closes[-40:]],
        "currency": info.get("currency", "USD"),
    }


# ---------------------------------------------------------------------------
# Cripto
# ---------------------------------------------------------------------------
def fetch_crypto(meta, markets_by_id):
    cg = meta["cg_id"]
    m = markets_by_id.get(cg, {})

    # Histórico diario 1 año para indicadores
    closes = []
    try:
        r = requests.get(
            f"https://api.coingecko.com/api/v3/coins/{cg}/market_chart",
            params={"vs_currency": "usd", "days": "365", "interval": "daily"},
            headers={"User-Agent": UA},
            timeout=30,
        )
        r.raise_for_status()
        closes = [float(p[1]) for p in r.json().get("prices", [])]
    except Exception as e:  # noqa: BLE001
        print(f"[warn] histórico cripto {cg}: {e}", file=sys.stderr)

    price = m.get("current_price")
    if price is None and closes:
        price = closes[-1]
    change_pct = m.get("price_change_percentage_24h")
    change = m.get("price_change_24h")

    s50 = sma(closes, 50)
    s200 = sma(closes, 200)
    rv = rsi(closes, 14)
    signal, score, reasons = build_signal(price, s50, s200, rv)

    return {
        "symbol": meta["symbol"],
        "name": meta["name"],
        "type": "crypto",
        "price": safe_round(price, 2),
        "change": safe_round(change),
        "changePct": safe_round(change_pct),
        "dayHigh": safe_round(m.get("high_24h")),
        "dayLow": safe_round(m.get("low_24h")),
        "week52High": safe_round(m.get("ath")),
        "week52Low": safe_round(m.get("atl"), 6),
        "volume": m.get("total_volume"),
        "marketCap": m.get("market_cap"),
        "circulatingSupply": m.get("circulating_supply"),
        "ath": safe_round(m.get("ath")),
        "athChangePct": safe_round(m.get("ath_change_percentage")),
        "sma50": safe_round(s50),
        "sma200": safe_round(s200),
        "rsi": safe_round(rv, 1),
        "signal": signal,
        "signalScore": score,
        "signalReasons": reasons,
        "spark": [safe_round(c) for c in closes[-40:]],
        "currency": "USD",
    }


def fetch_crypto_markets():
    ids = ",".join(c["cg_id"] for c in CRYPTOS)
    r = requests.get(
        "https://api.coingecko.com/api/v3/coins/markets",
        params={"vs_currency": "usd", "ids": ids},
        headers={"User-Agent": UA},
        timeout=30,
    )
    r.raise_for_status()
    return {m["id"]: m for m in r.json()}


# ---------------------------------------------------------------------------
def main():
    assets = []

    for meta in STOCKS:
        try:
            assets.append(fetch_stock(meta))
            print(f"[ok] {meta['symbol']}")
        except Exception as e:  # noqa: BLE001
            print(f"[err] {meta['symbol']}: {e}", file=sys.stderr)
        time.sleep(1)

    try:
        markets = fetch_crypto_markets()
    except Exception as e:  # noqa: BLE001
        print(f"[err] coingecko markets: {e}", file=sys.stderr)
        markets = {}

    for meta in CRYPTOS:
        try:
            assets.append(fetch_crypto(meta, markets))
            print(f"[ok] {meta['symbol']}")
        except Exception as e:  # noqa: BLE001
            print(f"[err] {meta['symbol']}: {e}", file=sys.stderr)
        time.sleep(1)

    out = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "assets": assets,
    }
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"[done] {len(assets)} activos -> data.json")


if __name__ == "__main__":
    main()
