"""chartink.py — scrapes all scan results from Chartink's internal API.

ROOT CAUSE FOUND: "daily close > 1 day ago daily close" breaks Chartink's
parser with scan_error. test-1 (857 stocks, no yesterday-compare) worked;
test-2 (added that exact line) broke immediately. This file tests two
alternate syntaxes for the same "closed up vs yesterday" condition to
find one Chartink actually accepts.
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
    # ── Baseline that we know works (857 stocks) ─────────────────────────────
    "test-1": {"label": "TEST1 (known working baseline)",
               "scan_clause": "( {cash} daily sma( daily volume * daily close ,20 ) > 50000000 and daily close > daily sma( daily close ,50 ) )"},

    # ── FIX ATTEMPT A: drop "daily" on the second operand ───────────────────
    "fix-a": {"label": "FIXA (drop daily on 2nd operand)",
              "scan_clause": "( {cash} daily sma( daily volume * daily close ,20 ) > 50000000 and daily close > daily sma( daily close ,50 ) and daily close > 1 day ago close )"},

    # ── FIX ATTEMPT B: wrap the historical term in parentheses ──────────────
    "fix-b": {"label": "FIXB (parenthesized ago term)",
              "scan_clause": "( {cash} daily sma( daily volume * daily close ,20 ) > 50000000 and daily close > daily sma( daily close ,50 ) and ( 1 day ago daily close ) < daily close )"},

    # ── FIX ATTEMPT C: use latest/current keyword style some scans use ──────
    "fix-c": {"label": "FIXC (latest close vs ago)",
              "scan_clause": "( {cash} daily sma( daily volume * daily close ,20 ) > 50000000 and daily close > daily sma( daily close ,50 ) and latest close > 1 day ago close )"},

    # ── Real scans continue running normally ─────────────────────────────────
    "contraction": {"label": "Contraction",       "scan_clause": "( {cash} ( daily sma( daily volume * daily close ,100 ) > 100000000 and daily sma( daily volume * daily close ,20 ) > 100000000 ) and not ( daily countstreak( 20 , daily sma( daily close ,20 ) < daily sma( daily close ,50 ) ) >= 20 or daily countstreak( 20 , daily sma( daily close ,50 ) < 1 day ago daily sma( daily close ,50 ) ) >= 20 or daily close < daily sma( daily close ,50 ) - daily avg true range( 50 ) or daily close < daily sma( daily close ,50 ) ) and ( daily close > daily sma( daily close ,100 ) or daily close > daily sma( daily close ,200 ) ) )"},
    "ppc":         {"label": "PPC",               "scan_clause": "( {cash} ( daily sma( daily volume * daily close ,20 ) > 100000000 and daily sma( daily volume * daily close ,100 ) > 100000000 ) and not ( daily countstreak( 20 , daily sma( daily close ,20 ) < daily sma( daily close ,50 ) ) >= 20 or daily countstreak( 20 , daily sma( daily close ,50 ) < 1 day ago daily sma( daily close ,50 ) ) >= 20 or daily close < daily sma( daily close ,50 ) or daily close < daily sma( daily close ,50 ) - daily avg true range( 50 ) ) and ( daily close > daily sma( daily close ,100 ) or daily close > daily sma( daily close ,200 ) ) and ( daily volume > daily sma( daily volume ,5 ) * 1.5 or daily volume > daily sma( daily volume ,20 ) * 1.5 or daily volume > daily sma( daily volume ,100 ) * 1.5 ) and daily close > 1 day ago daily close and ( daily avg true range( 1 ) > daily avg true range( 20 ) * 1.5 or daily avg true range( 1 ) > daily avg true range( 5 ) * 1.5 ) )"},
    "npc":         {"label": "NPC",               "scan_clause": "( {cash} daily close < 1 day ago daily close and daily sma( daily volume * daily close ,20 ) > 100000000 and daily sma( daily volume * daily close ,100 ) > 100000000 and ( daily avg true range( 1 ) > daily avg true range( 20 ) * 1.5 or daily avg true range( 1 ) > daily avg true range( 5 ) * 1.5 ) and ( daily volume > daily sma( daily volume ,5 ) * 1.5 or daily volume > daily sma( daily volume ,20 ) * 1.5 or daily volume > daily sma( daily volume ,100 ) * 1.5 ) and daily sma( daily close ,1 ) < 1 day ago daily sma( daily close ,1 ) )"},
    "bigmover":    {"label": "Big Movers",        "scan_clause": "( {cash} daily close > min( 126 , daily low ) * 1.7 and daily sma( daily volume * daily close ,50 ) > 70000000 and daily sma( daily volume * daily close ,100 ) > 70000000 )"},
    "indstrong":   {"label": "India Strong",      "scan_clause": "( {cash} daily sma( daily volume * daily close ,100 ) > 500000000 and daily sma( daily volume * daily close ,20 ) > 500000000 and not ( daily countstreak( 20 , daily sma( daily close ,20 ) < daily sma( daily close ,50 ) ) >= 20 or daily countstreak( 20 , daily sma( daily close ,50 ) < 1 day ago daily sma( daily close ,50 ) ) >= 20 or daily close < daily sma( daily close ,50 ) - daily avg true range( 50 ) or daily close < daily sma( daily close ,50 ) ) and ( daily close > daily sma( daily close ,100 ) or daily close > daily sma( daily close ,200 ) ) and not ( daily countstreak( 15 , daily close < daily sma( daily close ,20 ) ) >= 15 or daily countstreak( 15 , daily close < daily sma( daily close ,50 ) ) >= 15 or daily countstreak( 30 , daily close > daily sma( daily close ,20 ) ) >= 30 or daily countstreak( 30 , daily close > daily sma( daily close ,50 ) ) >= 30 ) )"},
    "newstock":    {"label": "New Stocks (IPO)",  "scan_clause": "( {cash} daily close > 0 and not ( 120 days ago daily close > 0 ) )"},
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

                if sid.startswith("test-") or sid.startswith("fix-"):
                    log.info("=" * 50)
                    log.info("DEBUG %s HTTP status: %d", sid, resp.status_code)
                    log.info("DEBUG %s raw response: %s", sid, resp.text[:300])
                    log.info("=" * 50)

                d    = resp.json()
                syms = [x["nsecode"].strip().upper() for x in d.get("data", []) if x.get("nsecode")]
                results[sid] = syms
                log.info("  %-30s -> %d stocks", cfg["label"], len(syms))
                time.sleep(1.5)
            except Exception as e:
                log.error("Scan %s failed: %s", sid, e)
                results[sid] = []

    return results
