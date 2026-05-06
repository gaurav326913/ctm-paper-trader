"""
nse.py
Fetches from NSE's public endpoints:
  - Closing / opening prices
  - ATR (Average True Range) from historical OHLC
  - Nifty 50 health check vs 200 DMA

No API key needed.

200 DMA fetch strategy:
  1. NSE historical endpoint (primary)
  2. Stooq CSV (fallback — no rate limits, works from GitHub Actions)
  3. 52-week midpoint proxy (last resort)
"""

import logging, time, statistics, csv, io
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
        url  = (f"https://www.nseindia.com/api/historical/cm/equity"
                f"?symbol={symbol}&series=[%22EQ%22]&duration=60")
        r    = _sess.get(url, timeout=20)
        data = (_safe_json(r) or {}).get("data", [])
        if len(data) < period + 1:
            return None

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
        time.sleep(0.4)
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


def _get_nifty_200dma_from_nse() -> float | None:
    """Try NSE historical endpoint for Nifty 200 DMA."""
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
                log.warning("Only %d days of Nifty history from NSE", len(hist))
                continue
            closes   = sorted(hist, key=lambda x: x.get("EOD_TIMESTAMP", ""))
            last_200 = [float(x["EOD_CLOSE_INDEX_VAL"]) for x in closes[-200:]]
            return round(statistics.mean(last_200), 2)
        except Exception as e:
            log.warning("NSE history endpoint failed: %s", e)
            time.sleep(2)
    return None


def _get_nifty_200dma_from_stooq() -> float | None:
    """
    Fallback: fetch Nifty 50 closes from Stooq CSV API.
    Stooq is free, no auth, no rate limits — works reliably from GitHub Actions.
    """
    try:
        url = "https://stooq.com/q/d/l/?s=%5Ensei&i=d"
        r   = requests.get(url, timeout=20,
                           headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            log.warning("Stooq returned HTTP %d", r.status_code)
            return None

        reader = csv.DictReader(io.StringIO(r.text))
        closes = []
        for row in reader:
            try:
                closes.append(float(row["Close"]))
            except (KeyError, ValueError):
                continue

        if len(closes) < 200:
            log.warning("Stooq returned only %d rows", len(closes))
            return None

        sma200 = round(statistics.mean(closes[-200:]), 2)
        log.info("Stooq: Nifty 200 DMA = %.2f (from %d days)", sma200, len(closes))
        return sma200

    except Exception as e:
        log.warning("Stooq Nifty 200 DMA failed: %s", e)
        return None


def _nifty_above_52w_midpoint(current: float) -> bool:
    """
    Last-resort health proxy: is Nifty above the midpoint of its 52-week range?
    Used only when all DMA data sources fail.
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
            log.info("Nifty 52w fallback: %.2f–%.2f  midpoint=%.2f  current=%.2f — %s",
                     low52, high52, midpoint, current,
                     "ABOVE MID (proxy healthy)" if current > midpoint else "BELOW MID (proxy unhealthy)")
            return current > midpoint
    except Exception as e:
        log.warning("52-week fallback also failed: %s", e)
    return True


def is_market_healthy() -> bool:
    """
    Returns True if Nifty 50 is above its 200-day SMA.

    Fetch strategy (in order):
      1. NSE historical endpoint
      2. Stooq CSV (reliable from GitHub Actions, no rate limits)
      3. 52-week midpoint proxy
      4. Final failsafe: True (don't block trades on data errors)
    """
    _init()

    current = _get_nifty_current()
    if not current:
        log.warning("Could not fetch Nifty current price — assuming healthy")
        return True

    # Try NSE first
    sma200 = _get_nifty_200dma_from_nse()

    # Fallback to Stooq
    if not sma200:
        log.info("NSE history unavailable — trying Stooq...")
        sma200 = _get_nifty_200dma_from_stooq()

    if sma200:
        healthy = current > sma200
        log.info("Nifty health: %.2f vs 200 DMA %.2f — %s",
                 current, sma200,
                 "HEALTHY ✓" if healthy else "UNHEALTHY ✗ — Tier 2 entries blocked")
        return healthy

    # Last resort: 52-week midpoint
    log.warning("200 DMA unavailable from all sources — using 52-week midpoint proxy")
    return _nifty_above_52w_midpoint(current)
