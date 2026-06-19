"""chartink.py — scrapes all scan results from Chartink's internal API.

SCAN QUALITY FIX (June 2026):
- Contraction: added explicit range-contraction filters (ATR shrinking)
  and SMA-trending-up checks. Was returning 750+ stocks; should now
  return 50-150 on a typical day.
- PPC: tightened volume to 2x 20-day average (was 1.5x on any of 3
  windows). Added 50 DMA trending up + must be above 100 DMA.
  Was returning 888 stocks; should now return 20-80 on a typical day.

SYNTAX FIX (June 2026, applied to all clauses):
  WRONG: daily close > 1 day ago daily close
  RIGHT: daily close > 1 day ago close
  (drop the timeframe prefix on the historical/ago operand)
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
    # Close above 20 & 50 DMA, 20 DMA above 50 DMA, closed up vs yesterday,
    # ATR expanding (momentum present), close in top 30% of today's range.
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
            "and daily close > daily low + ( daily high - daily low ) * 0.30 )"
        ),
    },

    # ── Champion Weekly ───────────────────────────────────────────────────────
    # Same logic on weekly timeframe — strongest trend signal in the system.
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
            "and weekly close > weekly low + ( weekly high - weekly low ) * 0.30 )"
        ),
    },

    # ── Contraction (TIGHTENED) ───────────────────────────────────────────────
    # Stock in uptrend (above 50 DMA, both 20 & 50 DMA trending up day-over-day)
    # AND range explicitly contracting:
    #   - 5-day ATR < 20-day ATR  (coiling over the past week vs past month)
    #   - today's ATR < 10-day ATR (today itself is a tight/narrow day)
    # This is the classic coiling-spring setup before a breakout.
    # Expected: 50-150 stocks on a typical trending market day.
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
            "and ( daily close > daily sma( daily close ,100 ) "
            "or daily close > daily sma( daily close ,200 ) ) )"
        ),
    },

    # ── PPC (TIGHTENED) ───────────────────────────────────────────────────────
    # Institutional accumulation day: stock in uptrend, volume is 2x the
    # 20-day average (was 1.5x on any of 3 windows — too loose), ATR expanding
    # confirms the volume is real momentum not just noise, closed up vs yesterday.
    # Expected: 20-80 stocks on a typical day.
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
    # High-volume down day — used as exit alert on open positions, not entry.
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
    # Stock trading well above its 126-day low with good liquidity.
    # No historical comparison — was the only working scan for 6 weeks.
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
    # in uptrend, not extended, not in a long downtrend.
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
    # Stocks listed in the last 120 days — excluded from entry qualification
    # (no ATR history), kept for dashboard visibility only.
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
