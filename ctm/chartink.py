"""chartink.py — scrapes all scan results from Chartink's internal API."""

import os, time, logging, requests
from bs4 import BeautifulSoup

log = logging.getLogger("ctm.chartink")

EMAIL    = os.environ.get("CHARTINK_EMAIL", "")
PASSWORD = os.environ.get("CHARTINK_PASSWORD", "")

# Base headers — browser-like
H = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
}

# Headers for the login POST — must look like a real browser form submission
H_LOGIN = {
    "User-Agent":   "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":       "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Content-Type": "application/x-www-form-urlencoded",
    "Origin":       "https://chartink.com",
    "Referer":      "https://chartink.com/login",
}

SCANS = {
    "champion-d":  {"label": "Champion Daily",    "scan_clause": "( {cash} ( daily sma( daily volume * daily close ,20 ) > 50000000 and daily sma( daily volume * daily close ,50 ) > 50000000 ) and not ( daily countstreak( 20 , daily sma( daily close ,20 ) < daily sma( daily close ,50 ) ) >= 20 or daily countstreak( 20 , daily sma( daily close ,50 ) < 1 day ago daily sma( daily close ,50 ) ) >= 20 or daily close < daily sma( daily close ,50 ) ) and daily close > daily sma( daily close ,10 ) and daily close > daily sma( daily close ,20 ) and daily sma( daily close ,10 ) > daily sma( daily close ,20 ) and daily close > 1 day ago daily close and daily avg true range( 1 ) > 0.6 * daily avg true range( 20 ) and daily close > daily low + ( daily high - daily low ) * 0.40 )"},
    "champion-w":  {"label": "Champion Weekly",   "scan_clause": "( {cash} ( weekly sma( weekly volume * weekly close ,20 ) > 50000000 and weekly sma( weekly volume * weekly close ,50 ) > 50000000 ) and not ( weekly countstreak( 20 , weekly sma( weekly close ,20 ) < weekly sma( weekly close ,50 ) ) >= 20 or weekly countstreak( 20 , weekly sma( weekly close ,50 ) < 1 week ago weekly sma( weekly close ,50 ) ) >= 20 or weekly close < weekly sma( weekly close ,50 ) ) and weekly close > weekly sma( weekly close ,10 ) and weekly close > weekly sma( weekly close ,20 ) and weekly sma( weekly close ,10 ) > weekly sma( weekly close ,20 ) and weekly close > 1 week ago weekly close and weekly avg true range( 1 ) > 0.6 * weekly avg true range( 20 ) and weekly close > weekly low + ( weekly high - weekly low ) * 0.40 )"},
    "contraction": {"label": "Contraction",       "scan_clause": "( {cash} ( daily sma( daily volume * daily close ,100 ) > 100000000 and daily sma( daily volume * daily close ,20 ) > 100000000 ) and not ( daily countstreak( 20 , daily sma( daily close ,20 ) < daily sma( daily close ,50 ) ) >= 20 or daily countstreak( 20 , daily sma( daily close ,50 ) < 1 day ago daily sma( daily close ,50 ) ) >= 20 or daily close < daily sma( daily close ,50 ) - daily avg true range( 50 ) or daily close < daily sma( daily close ,50 ) ) and ( daily close > daily sma( daily close ,100 ) or daily close > daily sma( daily close ,200 ) ) )"},
    "ppc":         {"label": "PPC",               "scan_clause": "( {cash} ( daily sma( daily volume * daily close ,20 ) > 100000000 and daily sma( daily volume * daily close ,100 ) > 100000000 ) and not ( daily countstreak( 20 , daily sma( daily close ,20 ) < daily sma( daily close ,50 ) ) >= 20 or daily countstreak( 20 , daily sma( daily close ,50 ) < 1 day ago daily sma( daily close ,50 ) ) >= 20 or daily close < daily sma( daily close ,50 ) or daily close < daily sma( daily close ,50 ) - daily avg true range( 50 ) ) and ( daily close > daily sma( daily close ,100 ) or daily close > daily sma( daily close ,200 ) ) and ( daily volume > daily sma( daily volume ,5 ) * 1.5 or daily volume > daily sma( daily volume ,20 ) * 1.5 or daily volume > daily sma( daily volume ,100 ) * 1.5 ) and daily close > 1 day ago daily close and ( daily avg true range( 1 ) > daily avg true range( 20 ) * 1.5 or daily avg true range( 1 ) > daily avg true range( 5 ) * 1.5 ) )"},
    "npc":         {"label": "NPC",               "scan_clause": "( {cash} daily close < 1 day ago daily close and daily sma( daily volume * daily close ,20 ) > 100000000 and daily sma( daily volume * daily close ,100 ) > 100000000 and ( daily avg true range( 1 ) > daily avg true range( 20 ) * 1.5 or daily avg true range( 1 ) > daily avg true range( 5 ) * 1.5 ) and ( daily volume > daily sma( daily volume ,5 ) * 1.5 or daily volume > daily sma( daily volume ,20 ) * 1.5 or daily volume > daily sma( daily volume ,100 ) * 1.5 ) and daily sma( daily close ,1 ) < 1 day ago daily sma( daily close ,1 ) )"},
    "bigmover":    {"label": "Big Movers",        "scan_clause": "( {cash} daily close > min( 126 , daily low ) * 1.7 and daily sma( daily volume * daily close ,50 ) > 70000000 and daily sma( daily volume * daily close ,100 ) > 70000000 )"},
    "indstrong":   {"label": "India Strong",      "scan_clause": "( {cash} daily sma( daily volume * daily close ,100 ) > 500000000 and daily sma( daily volume * daily close ,20 ) > 500000000 and not ( daily countstreak( 20 , daily sma( daily close ,20 ) < daily sma( daily close ,50 ) ) >= 20 or daily countstreak( 20 , daily sma( daily close ,50 ) < 1 day ago daily sma( daily close ,50 ) ) >= 20 or daily close < daily sma( daily close ,50 ) - daily avg true range( 50 ) or daily close < daily sma( daily close ,50 ) ) and ( daily close > daily sma( daily close ,100 ) or daily close > daily sma( daily close ,200 ) ) and not ( daily countstreak( 15 , daily close < daily sma( daily close ,20 ) ) >= 15 or daily countstreak( 15 , daily close < daily sma( daily close ,50 ) ) >= 15 or daily countstreak( 30 , daily close > daily sma( daily close ,20 ) ) >= 30 or daily countstreak( 30 , daily close > daily sma( daily close ,50 ) ) >= 30 ) )"},
    "newstock":    {"label": "New Stocks (IPO)",  "scan_clause": "( {cash} daily close > 0 and not ( 120 days ago daily close > 0 ) )"},
}


def fetch_all() -> dict:
    results = {}
    with requests.Session() as sess:

        # ── Step 1: Load the LOGIN page and grab its CSRF token ──────────────
        # Important: CSRF token must come from the login page, not the screener
        r_login_page = sess.get("https://chartink.com/login", headers=H, timeout=30)
        meta = BeautifulSoup(r_login_page.content, "html.parser").find("meta", {"name": "csrf-token"})
        if not meta:
            log.error("Chartink CSRF not found on login page")
            return {}
        csrf = meta["content"]
        log.info("Chartink CSRF token fetched OK")

        # ── Step 2: Login if credentials provided ────────────────────────────
        if EMAIL:
            time.sleep(2)   # brief pause — avoid triggering bot detection
            login_resp = sess.post(
                "https://chartink.com/login",
                data={"_token": csrf, "email": EMAIL, "password": PASSWORD},
                headers=H_LOGIN,
                timeout=30,
                allow_redirects=True,
            )
            log.info("Chartink login status: %d", login_resp.status_code)

            # Verify login succeeded by checking for logout link in page HTML
            logged_in = "logout" in login_resp.text.lower()
            log.info("Chartink logged in: %s", logged_in)

            if not logged_in:
                log.warning("Chartink login failed — scans will run as guest (limited results)")

            # ── Step 3: Re-fetch screener page to get fresh post-login CSRF ──
            time.sleep(1)
            r_screener = sess.get("https://chartink.com/screener/", headers=H, timeout=30)
            m2 = BeautifulSoup(r_screener.content, "html.parser").find("meta", {"name": "csrf-token"})
            if m2:
                csrf = m2["content"]
                log.info("Post-login CSRF refreshed OK")
            else:
                log.warning("Could not refresh post-login CSRF — using original token")
        else:
            log.warning("No Chartink credentials set — running as guest")
            # Still need screener CSRF for scan POSTs
            r_screener = sess.get("https://chartink.com/screener/", headers=H, timeout=30)
            m2 = BeautifulSoup(r_screener.content, "html.parser").find("meta", {"name": "csrf-token"})
            if m2:
                csrf = m2["content"]

        # ── Step 4: Run each scan ─────────────────────────────────────────────
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
