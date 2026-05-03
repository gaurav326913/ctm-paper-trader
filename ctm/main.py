"""
main.py
Detects whether it's the morning run (9:20 AM IST) or evening run (6 PM IST)
and executes the appropriate job.

Evening (6 PM):
  1. Nifty health check
  2. Run Chartink scans
  3. Queue qualifying candidates for tomorrow
  4. Update current prices + check SL/targets on open positions
  5. Rebuild dashboard

Morning (9:20 AM):
  1. Enter pending trades at today's open price with ATR-based SL/target
  2. Rebuild dashboard
"""

import logging, datetime, os, sys, pytz

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("ctm")

ROOT      = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_FILE = os.path.join(ROOT, "data", "trades.json")
DOCS_PATH = os.path.join(ROOT, "docs", "index.html")

sys.path.insert(0, ROOT)

IST = pytz.timezone("Asia/Kolkata")


def is_morning_run() -> bool:
    """True if current IST time is before noon — morning entry run."""
    now = datetime.datetime.now(IST)
    return now.hour < 12


def run_evening():
    """6 PM job: scan Chartink, check market health, queue candidates, update prices."""
    log.info("=" * 55)
    log.info("EVENING RUN — %s", datetime.date.today().strftime("%d %b %Y"))
    log.info("=" * 55)

    from ctm.chartink import fetch_all
    from ctm.nse import get_closing_prices, is_market_healthy
    from ctm.engine import load, save, queue_candidates, check_exits, update_prices, update_equity_curve
    from ctm.dashboard import write_v3 as write_dash

    log.info("Step 1/5: Nifty health check...")
    healthy = is_market_healthy()

    log.info("Step 2/5: Running Chartink scans...")
    scan_results = fetch_all()
    all_syms = list({s for syms in scan_results.values() for s in syms})
    log.info("  %d unique symbols across all scans", len(all_syms))

    log.info("Step 3/5: Loading data + fetching closing prices...")
    data      = load(DATA_FILE)
    open_syms = [p["symbol"] for p in data["positions"] if p["status"] == "open"]
    prices    = get_closing_prices(list(set(all_syms + open_syms)))

    log.info("Step 4/5: Checking SL / Target exits...")
    closed = check_exits(data, prices)
    update_prices(data, prices)
    log.info("  Closed today: %d", len(closed))

    log.info("Step 5/5: Queuing candidates for tomorrow's open...")
    queued = queue_candidates(data, scan_results, datetime.date.today().isoformat(), healthy)

    update_equity_curve(data)
    save(data, DATA_FILE)

    n_open = sum(1 for p in data["positions"] if p["status"] == "open")
    log.info("Status: Open=%d  Pending=%d  Closed today=%d  Queued=%d",
             n_open, len(data.get("pending", [])), len(closed), len(queued))

    write_dash(data, scan_results, DOCS_PATH, healthy)
    log.info("Dashboard updated.")
    log.info("Evening run complete.")


def run_morning():
    """9:20 AM job: enter pending trades at today's open price."""
    log.info("=" * 55)
    log.info("MORNING RUN — %s", datetime.date.today().strftime("%d %b %Y"))
    log.info("=" * 55)

    from ctm.nse import get_closing_prices, get_atrs
    from ctm.engine import load, save, enter_pending, update_equity_curve
    from ctm.dashboard import write_v3 as write_dash
    from ctm.chartink import SCANS

    data    = load(DATA_FILE)
    pending = data.get("pending", [])

    if not pending:
        log.info("No pending trades — nothing to enter. Morning run complete.")
        return

    symbols = [p["symbol"] for p in pending]
    log.info("Pending trades to enter: %d — %s", len(symbols), ", ".join(symbols))

    log.info("Step 1/2: Fetching open prices + ATR...")
    open_prices = get_closing_prices(symbols)   # at 9:20 AM this gives the open/early price
    atrs        = get_atrs(symbols)

    log.info("Step 2/2: Entering trades...")
    entered = enter_pending(data, open_prices, atrs)
    log.info("  Entered: %d trades", len(entered))

    update_equity_curve(data)
    save(data, DATA_FILE)

    # Rebuild dashboard with empty scan_results (morning has no scan data)
    scan_results = {sid: [] for sid in SCANS}
    write_dash(data, scan_results, DOCS_PATH, healthy)
    log.info("Dashboard updated.")
    log.info("Morning run complete.")


def main():
    if is_morning_run():
        run_morning()
    else:
        run_evening()


if __name__ == "__main__":
    main()
