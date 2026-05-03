"""main.py — orchestrates the full daily run."""

import logging, datetime, os, sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("ctm")

# Ensure repo root is on the path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

DATA_FILE  = os.path.join(ROOT, "data", "trades.json")
DOCS_PATH  = os.path.join(ROOT, "docs", "index.html")


def main():
    log.info("=" * 55)
    log.info("CTM Paper Trader -- %s", datetime.date.today().strftime("%d %b %Y"))
    log.info("=" * 55)

    from ctm.chartink import fetch_all
    from ctm.nse_prices import get_closing_prices
    from ctm.engine import load, save, check_exits, enter_trades, update_equity_curve
    from ctm.dashboard import write as write_dashboard

    log.info("Step 1/5: Running Chartink scans...")
    scan_results = fetch_all()
    all_syms = list({s for syms in scan_results.values() for s in syms})
    log.info("  %d unique symbols across all scans", len(all_syms))

    log.info("Step 2/5: Loading existing trades...")
    data = load(DATA_FILE)
    open_syms = [p["symbol"] for p in data["positions"] if p["status"] == "open"]

    log.info("Step 3/5: Fetching NSE closing prices...")
    prices = get_closing_prices(list(set(all_syms + open_syms)))

    log.info("Step 4/5: Checking SL / Target exits...")
    closed_today = check_exits(data, prices)
    log.info("  Closed today: %d", len(closed_today))

    log.info("Step 5/5: Entering new paper trades...")
    new_trades = enter_trades(data, scan_results, prices, datetime.date.today().isoformat())
    log.info("  New trades: %d", len(new_trades))

    update_equity_curve(data)
    save(data, DATA_FILE)

    n_open = sum(1 for p in data["positions"] if p["status"] == "open")
    n_cl   = sum(1 for p in data["positions"] if p["status"] == "closed")
    rpnl   = sum(p["pnl"] for p in data["positions"] if p.get("pnl"))
    log.info("Portfolio: Open=%d  Closed=%d  Realized P&L=Rs%+.0f", n_open, n_cl, rpnl)

    log.info("Generating dashboard...")
    write_dashboard(data, scan_results, DOCS_PATH)
    log.info("Dashboard written to %s", DOCS_PATH)

    log.info("=" * 55)
    log.info("Done.")
    log.info("=" * 55)


if __name__ == "__main__":
    main()
