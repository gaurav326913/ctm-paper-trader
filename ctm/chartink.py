"""chartink.py — scrapes all scan results from Chartink's internal API.

FINAL SCAN QUALITY (June 2026):

KEY ADDITION: "within 5% of 52-week high" filter on Champion Daily
and Champion Weekly.
  Clause: daily close > daily max( 252 , daily high ) * 0.95
  Why: stocks near 52-week highs are in strong hands — institutions
  haven't distributed, there's no overhead supply, and breakouts from
  these levels have the highest follow-through rate in swing trading.
  This is the core filter used by IBD/CAN SLIM and most professional
  momentum systems. Adding it to Champion D/W reduces those scans from
  300-400 stocks to a much tighter, higher-quality universe.

FULL CHANGE HISTORY:
  1. Fixed "N day ago daily X" → "N day ago X" syntax (Chartink parser fix)
  2. Tightened Contraction: added ATR-shrinking + SMA-trending-up checks
     + "within 3% of 20-day high"
  3. Tightened PPC: volume 2x 20-day avg (was 1.5x any window), ATR 1.5x
  4. Added 52-week high proximity to Champion Daily + Weekly (this update)
"""

import os, time, logging, requests
from bs4 import BeautifulSoup

log = logging.getLogger("ctm.chartink")

EMAIL    = os.environ.get("CHARTINK_EMAIL", "")
PASSWORD = os.environ.get("CHARTINK_PASSWORD", "")

H = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
}

H_LOGIN = {
    "User-Agent":   "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":       "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Content-Type": "application/x-www-form-urlencoded",
    "Origin":       "https://chartink.com",
    "Referer":      "https://chartink.com/login",
}

SCANS = {
    # ── Champion Daily ────────────────────────────────────────────────────────
    # Trend: close above 20 & 50 DMA, 20 DMA above 50 DMA (sequence intact)
    # Momentum: closed up vs yesterday, ATR expanding, strong close in range
    # Structure: within 5% of 52-week high (near highs, not recovering)
    # Liquidity: 20 & 50 day avg turnover > 50M
    "champion-d": {
        "label": "Champion Daily",
        "scan_clause": (
            "( {cash} "
            "( daily sma( daily volume * daily close ,20 ) > 50000000 "
            "and daily sma( daily volume * daily close ,50 ) > 50000000 ) "
            "and daily close > daily sma( daily close ,20 ) "
            "and daily close > daily sma( daily close ,50 ) "
            "and daily sma( daily close ,20 ) > daily sma( daily close ,50 ) "
            "and daily close > 1 day ago close "
            "and daily avg true range( 1 ) > 0.4 * daily avg true range( 20 ) "
            "and daily close > daily low + ( daily high - daily low ) * 0.30 "
            "and daily close > daily max( 252 , daily high ) * 0.95 )"
        ),
    },

    # ── Champion Weekly ───────────────────────────────────────────────────────
    # Same logic on weekly timeframe + within 5% of 52-week high.
    # Weekly confirmation is the strongest signal in the system —
    # means institutional money has been accumulating for weeks.
    "champion-w": {
        "label": "Champion Weekly",
        "scan_clause": (
            "( {cash} "
            "( weekly sma( weekly volume * weekly close ,20 ) > 50000000 "
            "and weekly sma( weekly volume * weekly close ,50 ) > 50000000 ) "
            "and weekly close > weekly sma( weekly close ,20 ) "
            "and weekly close > weekly sma( weekly close ,50 ) "
            "and weekly sma( weekly close ,20 ) > weekly sma( weekly close ,50 ) "
            "and weekly close > 1 week ago close "
            "and weekly avg true range( 1 ) > 0.4 * weekly avg true range( 20 ) "
            "and weekly close > weekly low + ( weekly high - weekly low ) * 0.30 "
            "and daily close > daily max( 252 , daily high ) * 0.95 )"
        ),
    },

    # ── Contraction ───────────────────────────────────────────────────────────
    # Stock in uptrend (20 & 50 DMA both trending up day-over-day),
    # range explicitly contracting (5-day ATR < 20-day ATR, today tight),
    # coiling within 3% of 20-day high (near recent highs, not pulling back deep).
    # Classic flag/base formation before a breakout.
    "contraction": {
        "label": "Contraction",
        "scan_clause": (
            "( {cash} "
            "( daily sma( daily volume * daily close ,100 ) > 100000000 "
            "and daily sma( daily volume * daily close ,20 ) > 100000000 ) "
            "and daily close > daily sma( daily close ,50 ) "
            "and daily sma( daily close ,50 ) > 1 day ago sma( daily close ,50 ) "
            "and daily close > daily sma( daily close ,20 ) "
            "and daily sma( daily close ,20 ) > 1 day ago sma( daily close ,20 ) "
            "and daily avg true range( 5 ) < daily avg true range( 20 ) "
            "and daily avg true range( 1 ) < daily avg true range( 10 ) "
            "and daily close > daily max( 20 , daily high ) * 0.97 "
            "and ( daily close > daily sma( daily close ,100 ) "
            "or daily close > daily sma( daily close ,200 ) ) )"
        ),
    },

    # ── PPC ───────────────────────────────────────────────────────────────────
    # Institutional accumulation day: volume 2x the 20-day average,
    # ATR expanding (volume is real momentum not noise), stock in uptrend,
    # 50 DMA trending up, above 100 DMA, closed up vs yesterday.
    "ppc": {
        "label": "PPC",
        "scan_clause": (
            "( {cash} "
            "( daily sma( daily volume * daily close ,20 ) > 100000000 "
            "and daily sma( daily volume * daily close ,100 ) > 100000000 ) "
            "and daily close > daily sma( daily close ,50 ) "
            "and daily sma( daily close ,50 ) > 1 day ago sma( daily close ,50 ) "
            "and daily close > daily sma( daily close ,100 ) "
            "and daily close > 1 day ago close "
            "and daily volume > daily sma( daily volume ,20 ) * 2.0 "
            "and daily avg true range( 1 ) > daily avg true range( 20 ) * 1.5 )"
        ),
    },

    # ── NPC ───────────────────────────────────────────────────────────────────
    # High-volume down day. Used as EXIT ALERT on open positions only.
    # Never used as an entry signal.
    "npc": {
        "label": "NPC",
        "scan_clause": (
            "( {cash} "
            "daily close < 1 day ago close "
            "and daily sma( daily volume * daily close ,20 ) > 100000000 "
            "and daily sma( daily volume * daily close ,100 ) > 100000000 "
            "and ( daily avg true range( 1 ) > daily avg true range( 20 ) * 1.5 "
            "or daily avg true range( 1 ) > daily avg true range( 5 ) * 1.5 ) "
            "and ( daily volume > daily sma( daily volume ,5 ) * 1.5 "
            "or daily volume > daily sma( daily volume ,20 ) * 1.5 "
            "or daily volume > daily sma( daily volume ,100 ) * 1.5 ) "
            "and daily sma( daily close ,1 ) < 1 day ago sma( daily close ,1 ) )"
        ),
    },

    # ── Big Movers ────────────────────────────────────────────────────────────
    # Trading well above 126-day low with good liquidity.
    # Used only in combo with Champion Daily (Tier 2 in engine.py).
    "bigmover": {
        "label": "Big Movers",
        "scan_clause": (
            "( {cash} "
            "daily close > min( 126 , daily low ) * 1.7 "
            "and daily sma( daily volume * daily close ,50 ) > 70000000 "
            "and daily sma( daily volume * daily close ,100 ) > 70000000 )"
        ),
    },

    # ── India Strong ──────────────────────────────────────────────────────────
    # Large-cap quality filter: very high liquidity (500M turnover),
    # in uptrend, 50 DMA trending up, not overextended, not in long downtrend.
    # Used as a combo filter — qualifies stocks when paired with PPC (Tier 2)
    # or Champion Daily (Tier 1).
    "indstrong": {
        "label": "India Strong",
        "scan_clause": (
            "( {cash} "
            "daily sma( daily volume * daily close ,100 ) > 500000000 "
            "and daily sma( daily volume * daily close ,20 ) > 500000000 "
            "and not ( "
            "daily countstreak( 20 , daily sma( daily close ,20 ) < daily sma( daily close ,50 ) ) >= 20 "
            "or daily sma( daily close ,50 ) < 1 day ago sma( daily close ,50 ) "
            "or daily close < daily sma( daily close ,50 ) - daily avg true range( 50 ) "
            "or daily close < daily sma( daily close ,50 ) ) "
            "and ( daily close > daily sma( daily close ,100 ) "
            "or daily close > daily sma( daily close ,200 ) ) "
            "and not ( "
            "daily countstreak( 15 , daily close < daily sma( daily close ,20 ) ) >= 15 "
            "or daily countstreak( 15 , daily close < daily sma( daily close ,50 ) ) >= 15 "
            "or daily countstreak( 30 , daily close > daily sma( daily close ,20 ) ) >= 30 "
            "or daily countstreak( 30 , daily close > daily sma( daily close ,50 ) ) >= 30 ) )"
        ),
    },

    # ── New Stocks (IPO) ──────────────────────────────────────────────────────
    # Stocks listed in the last 120 days.
    # Kept for dashboard visibility only — excluded from entry qualification
    # in engine.py since ATR history is insufficient for SL/target calculation.
    "newstock": {
        "label": "New Stocks (IPO)",
        "scan_clause": (
            "( {cash} "
            "daily close > 0 "
            "and not ( 120 days ago close > 0 ) )"
        ),
    },
}


def _get_csrf(sess: requests.Session, url: str) -> str | None:
    try:
        r    = sess.get(url, headers=H, timeout=30)
        meta = BeautifulSoup(r.content, "html.parser").find("meta", {"name": "csrf-token"})
        if meta:
            return meta["content"]
        log.warning("CSRF not found on %s", url)
        return None
    except Exception as e:
        log.error("Failed to fetch %s: %s", url, e)
        return None


def fetch_all() -> dict:
    results = {}
    with requests.Session() as sess:

        csrf = _get_csrf(sess, "https://chartink.com/screener/")
        if not csrf:
            log.error("Could not get Chartink CSRF — aborting")
            return {}
        log.info("Chartink CSRF fetched OK")

        if EMAIL:
            time.sleep(2)
            login_resp = sess.post(
                "https://chartink.com/login",
                data={"_token": csrf, "email": EMAIL, "password": PASSWORD},
                headers=H_LOGIN,
                timeout=30,
                allow_redirects=True,
            )
            log.info("Chartink login HTTP status: %d", login_resp.status_code)
            logged_in = "logout" in login_resp.text.lower()
            log.info("Chartink logged in: %s", logged_in)
            if not logged_in:
                log.warning("Chartink login failed — scans will run as guest (limited results)")

            time.sleep(1)
            fresh_csrf = _get_csrf(sess, "https://chartink.com/screener/")
            if fresh_csrf:
                csrf = fresh_csrf
                log.info("Post-login CSRF refreshed OK")
            else:
                log.warning("Could not refresh post-login CSRF — using original token")
        else:
            log.warning("No Chartink credentials set — running as guest")

        for sid, cfg in SCANS.items():
            try:
                resp = sess.post(
                    "https://chartink.com/screener/process",
                    data={"scan_clause": cfg["scan_clause"]},
                    headers={
                        **H,
                        "x-csrf-token": csrf,
                        "Referer": "https://chartink.com/screener/",
                    },
                    timeout=60,
                )
                d    = resp.json()
                syms = [x["nsecode"].strip().upper() for x in d.get("data", []) if x.get("nsecode")]
                results[sid] = syms
                log.info("  %-18s -> %d stocks", cfg["label"], len(syms))
                time.sleep(1.5)
            except Exception as e:
                log.error("Scan %s failed: %s", sid, e)
                results[sid] = []

    return results
