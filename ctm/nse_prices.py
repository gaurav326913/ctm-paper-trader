"""
nse_prices.py
Fetches end-of-day closing prices from NSE India's public endpoints.
No API key, no login, completely free.
"""

import logging
import requests

log = logging.getLogger("ctm.nse")

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com",
})


def _init_cookies():
    """NSE requires a cookie handshake before API calls."""
    try:
        SESSION.get("https://www.nseindia.com", timeout=15)
        SESSION.get("https://www.nseindia.com/market-data/live-equity-market", timeout=15)
    except Exception as e:
        log.warning("NSE cookie init warning: %s", e)


def get_closing_prices(symbols: list) -> dict:
    """
    Fetch closing prices for a list of NSE symbols.
    Returns {symbol: price}. Missing symbols are omitted.
    Falls back to quote API for individual symbols if bulk fetch fails.
    """
    if not symbols:
        return {}

    _init_cookies()
    prices = {}

    # Try bulk fetch first via NSE's market data API
    try:
        resp = SESSION.get(
            "https://www.nseindia.com/api/equity-stockIndices?index=SECURITIES%20IN%20F%26O",
            timeout=20
        )
        data = resp.json().get("data", [])
        nse_map = {row["symbol"]: row["lastPrice"] for row in data if "symbol" in row}
        for sym in symbols:
            if sym in nse_map:
                prices[sym] = float(str(nse_map[sym]).replace(",", ""))
    except Exception as e:
        log.warning("NSE bulk fetch failed: %s — falling back to individual quotes", e)

    # For any symbol not found in bulk, try individual quote API
    missing = [s for s in symbols if s not in prices]
    for sym in missing:
        try:
            resp = SESSION.get(
                f"https://www.nseindia.com/api/quote-equity?symbol={sym}",
                timeout=15
            )
            d = resp.json()
            price = (
                d.get("priceInfo", {}).get("lastPrice") or
                d.get("priceInfo", {}).get("close")
            )
            if price:
                prices[sym] = float(str(price).replace(",", ""))
                log.debug("Individual quote: %s = %.2f", sym, prices[sym])
        except Exception as e:
            log.warning("Could not fetch price for %s: %s", sym, e)

    log.info("Prices fetched: %d / %d symbols", len(prices), len(symbols))
    return prices
