"""
nse.py
Fetches from NSE's public endpoints:
  - Closing / opening prices
  - ATR (Average True Range) from historical OHLC
  - Nifty 50 health check vs 200 DMA
No API key needed.
"""

import logging, time, statistics
import requests

log = logging.getLogger("ctm.nse")

_sess = requests.Session()
_sess.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com",
})
_cookies_ready = False


def _init():
    global _cookies_ready
    if _cookies_ready:
        return
    try:
        _sess.get("https://www.nseindia.com", timeout=15)
        _sess.get("https://www.nseindia.com/market-data/live-equity-market", timeout=10)
        _cookies_ready = True
    except Exception as e:
        log.warning("NSE cookie init: %s", e)


def get_quote(symbol: str) -> dict:
    """Raw quote dict for a symbol."""
    _init()
    try:
        r = _sess.get(f"https://www.nseindia.com/api/quote-equity?symbol={symbol}", timeout=15)
        return r.json()
    except Exception as e:
        log.warning("Quote fetch failed for %s: %s", symbol, e)
        return {}


def get_closing_prices(symbols: list) -> dict:
    """
    Fetch last traded / closing prices for a list of symbols.
    Returns {symbol: price}.
    """
    if not symbols:
        return {}
    _init()
    prices = {}

    # Bulk fetch via F&O list (covers most liquid stocks)
    try:
        r    = _sess.get("https://www.nseindia.com/api/equity-stockIndices?index=SECURITIES%20IN%20F%26O", timeout=20)
        data = r.json().get("data", [])
        bulk = {row["symbol"]: float(str(row["lastPrice"]).replace(",", ""))
                for row in data if "symbol" in row and "lastPrice" in row}
        for sym in symbols:
            if sym in bulk:
                prices[sym] = bulk[sym]
    except Exception as e:
        log.warning("NSE bulk fetch failed: %s", e)

    # Individual quote for any not found in bulk
    for sym in [s for s in symbols if s not in prices]:
        try:
            d  = get_quote(sym)
            px = (d.get("priceInfo", {}).get("lastPrice") or
                  d.get("priceInfo", {}).get("close"))
            if px:
                prices[sym] = float(str(px).replace(",", ""))
            time.sleep(0.3)
        except Exception as e:
            log.warning("Individual price failed %s: %s", sym, e)

    log.info("Prices fetched: %d / %d", len(prices), len(symbols))
    return prices


def get_atr(symbol: str, period: int = 14) -> float | None:
    """
    Calculate ATR from NSE historical daily OHLC data.
    Uses Wilder's ATR formula over `period` days.
    Returns ATR as a price value (e.g. 45.30) or None if unavailable.
    """
    _init()
    try:
        # Fetch last 60 days of OHLC to comfortably calculate 14-day ATR
        url = (f"https://www.nseindia.com/api/historical/cm/equity"
               f"?symbol={symbol}&series=[%22EQ%22]&duration=60")
        r    = _sess.get(url, timeout=20)
        data = r.json().get("data", [])
        if len(data) < period + 1:
            return None

        # Sort ascending by date
        data = sorted(data, key=lambda x: x.get("CH_TIMESTAMP", ""))

        true_ranges = []
        for i in range(1, len(data)):
            high  = float(data[i]["CH_TRADE_HIGH_PRICE"])
            low   = float(data[i]["CH_TRADE_LOW_PRICE"])
            prev_close = float(data[i-1]["CH_CLOSING_PRICE"])
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low  - prev_close)
            )
            true_ranges.append(tr)

        if len(true_ranges) < period:
            return None

        # Wilder's smoothed ATR
        atr = statistics.mean(true_ranges[:period])
        for tr in true_ranges[period:]:
            atr = (atr * (period - 1) + tr) / period

        return round(atr, 2)

    except Exception as e:
        log.warning("ATR fetch failed for %s: %s", symbol, e)
        return None


def get_atrs(symbols: list, period: int = 14) -> dict:
    """Fetch ATR for multiple symbols. Returns {symbol: atr}."""
    result = {}
    for sym in symbols:
        atr = get_atr(sym, period)
        if atr:
            result[sym] = atr
        time.sleep(0.4)   # be polite to NSE
    log.info("ATRs fetched: %d / %d", len(result), len(symbols))
    return result


def is_market_healthy() -> bool:
    """
    Returns True if Nifty 50 is above its 200-day SMA.
    If the check fails for any reason, returns True (fail-safe — don't block trades on data error).
    """
    _init()
    try:
        # Get Nifty 50 current level
        r    = _sess.get("https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%2050", timeout=15)
        data = r.json().get("data", [])
        nifty_row = next((x for x in data if x.get("symbol") == "NIFTY 50"), None)
        if not nifty_row:
            log.warning("Nifty row not found — assuming market healthy")
            return True
        current = float(str(nifty_row["lastPrice"]).replace(",", ""))

        # Get Nifty historical data for 200 DMA
        url  = ("https://www.nseindia.com/api/historical/indicesHistory"
                "?indexType=NIFTY%2050&duration=250")
        r2   = _sess.get(url, timeout=20)
        hist = r2.json().get("data", {}).get("indexCloseOnlineRecords", [])
        if len(hist) < 200:
            log.warning("Not enough Nifty history (%d days) — assuming healthy", len(hist))
            return True

        closes = sorted(hist, key=lambda x: x.get("EOD_TIMESTAMP", ""))
        last_200 = [float(x["EOD_CLOSE_INDEX_VAL"]) for x in closes[-200:]]
        sma200   = round(statistics.mean(last_200), 2)

        healthy = current > sma200
        log.info("Nifty health: %.2f vs 200 DMA %.2f — %s",
                 current, sma200, "HEALTHY" if healthy else "UNHEALTHY — no new entries")
        return healthy

    except Exception as e:
        log.warning("Nifty health check failed: %s — assuming healthy", e)
        return True
