"""
nse.py
Fetches from NSE's public endpoints:
  - Closing / opening prices
  - ATR (Average True Range) from historical OHLC
  - Nifty 50 health check vs 200 DMA

No API key needed.

Fixes vs original:
  - is_market_healthy() now tries multiple endpoints for 200 DMA
  - Falls back to checking Nifty vs its 52-week range as a proxy if all historical endpoints fail
  - Session init retries on failure
  - Explicit response content-type check before .json() to avoid cryptic parse errors
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


def _safe_json(r) -> dict | list | None:
    """Parse JSON only if response looks valid. Returns None on failure."""
    ct = r.headers.get("Content-Type", "")
    if r.status_code != 200:
        log.warning("HTTP %d from %s", r.status_code, r.url)
        return None
    if "json" not in ct and "javascript" not in ct:
        log.warning("Unexpected Content-Type '%s' from %s — likely HTML error page", ct, r.url)
        return None
    try:
        return r.json()
    except Exception as e:
        log.warning("JSON parse failed from %s: %s", r.url, e)
        return None


def _init():
    global _cookies_ready
    if _cookies_ready:
        return
    for attempt in range(3):
        try:
            _sess.get("https://www.nseindia.com", timeout=15)
            _sess.get("https://www.nseindia.com/market-data/live-equity-market", timeout=10)
            _cookies_ready = True
            return
        except Exception as e:
            log.warning("NSE cookie init attempt %d failed: %s", attempt + 1, e)
            time.sleep(2)
    log.warning("NSE session init failed after 3 attempts — proceeding anyway")


def get_quote(symbol: str) -> dict:
    """Raw quote dict for a symbol."""
    _init()
    try:
        r = _sess.get(f"https://www.nseindia.com/api/quote-equity?symbol={symbol}", timeout=15)
        return _safe_json(r) or {}
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
        data = (_safe_json(r) or {}).get("data", [])
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
        url = (f"https://www.nseindia.com/api/historical/cm/equity"
               f"?symbol={symbol}&series=[%22EQ%22]&duration=60")
        r    = _sess.get(url, timeout=20)
        data = (_safe_json(r) or {}).get("data", [])
        if len(data) < period + 1:
            return None

        # Sort ascending by date
        data = sorted(data, key=lambda x: x.get("CH_TIMESTAMP", ""))

        true_ranges = []
        for i in range(1, len(data)):
            high       = float(data[i]["CH_TRADE_HIGH_PRICE"])
            low        = float(data[i]["CH_TRADE_LOW_PRICE"])
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


def _get_nifty_current() -> float | None:
    """Fetch current Nifty 50 level. Returns None on failure."""
    try:
        r    = _sess.get("https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%2050", timeout=15)
        data = (_safe_json(r) or {}).get("data", [])
        row  = next((x for x in data if x.get("symbol") == "NIFTY 50"), None)
        if row:
            return float(str(row["lastPrice"]).replace(",", ""))
    except Exception as e:
        log.warning("Nifty current price fetch failed: %s", e)
    return None


def _get_nifty_200dma() -> float | None:
    """
    Fetch Nifty 50 historical closes and compute 200 DMA.
    Tries two endpoints — NSE blocks GitHub Actions IPs intermittently.
    Returns None if both fail.
    """
    endpoints = [
        ("https://www.nseindia.com/api/historical/indicesHistory"
         "?indexType=NIFTY%2050&duration=250"),
        ("https://www.nseindia.com/api/historical/indicesHistory"
         "?indexType=NIFTY%2050&duration=300"),
    ]
    for url in endpoints:
        try:
            r    = _sess.get(url, timeout=25)
            body = _safe_json(r)
            if not body:
                continue
            hist = body.get("data", {}).get("indexCloseOnlineRecords", [])
            if len(hist) < 200:
                log.warning("Only %d days of Nifty history returned", len(hist))
                continue
            closes   = sorted(hist, key=lambda x: x.get("EOD_TIMESTAMP", ""))
            last_200 = [float(x["EOD_CLOSE_INDEX_VAL"]) for x in closes[-200:]]
            return round(statistics.mean(last_200), 2)
        except Exception as e:
            log.warning("Nifty history endpoint failed (%s): %s", url, e)
            time.sleep(2)

    return None


def _nifty_above_52w_midpoint(current: float) -> bool:
    """
    Fallback health proxy: is Nifty above the midpoint of its 52-week range?
    If yes, treat as healthy. Used only when 200 DMA fetch fails.
    """
    try:
        r    = _sess.get("https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%2050", timeout=15)
        data = (_safe_json(r) or {}).get("data", [])
        row  = next((x for x in data if x.get("symbol") == "NIFTY 50"), None)
        if not row:
            return True
        high52 = float(str(row.get("yearHigh", 0)).replace(",", ""))
        low52  = float(str(row.get("yearLow",  0)).replace(",", ""))
        if high52 and low52:
            midpoint = (high52 + low52) / 2
            log.info("Nifty 52w range fallback: %.2f–%.2f  midpoint=%.2f  current=%.2f — %s",
                     low52, high52, midpoint, current,
                     "ABOVE MID (proxy healthy)" if current > midpoint else "BELOW MID (proxy unhealthy)")
            return current > midpoint
    except Exception as e:
        log.warning("52-week fallback also failed: %s", e)
    return True   # final failsafe — don't block trades on data errors


def is_market_healthy() -> bool:
    """
    Returns True if Nifty 50 is above its 200-day SMA.

    Strategy:
      1. Fetch current Nifty level
      2. Try to compute 200 DMA from historical endpoint
      3. If historical fetch fails, fall back to 52-week midpoint as proxy
      4. If everything fails, return True (don't block trades on data errors)
    """
    _init()

    current = _get_nifty_current()
    if not current:
        log.warning("Could not fetch Nifty current price — assuming healthy")
        return True

    sma200 = _get_nifty_200dma()

    if sma200:
        healthy = current > sma200
        log.info("Nifty health: %.2f vs 200 DMA %.2f — %s",
                 current, sma200, "HEALTHY ✓" if healthy else "UNHEALTHY ✗ — Tier 2 entries blocked")
        return healthy

    # Historical endpoint failed — use 52-week midpoint as proxy
    log.warning("200 DMA unavailable — using 52-week midpoint as health proxy")
    return _nifty_above_52w_midpoint(current)
