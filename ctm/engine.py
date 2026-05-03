"""engine.py — paper trade entry, exit, and persistence."""

import json, os, time, datetime, logging

log = logging.getLogger("ctm.engine")

SL_PCT   = float(os.environ.get("STOP_LOSS_PCT",  5.0))
TGT_PCT  = float(os.environ.get("TARGET_PCT",    15.0))
POS_SIZE = int(os.environ.get("POSITION_SIZE",  25000))
MAX_POS  = int(os.environ.get("MAX_POSITIONS",     20))
MIN_SCANS = int(os.environ.get("MIN_SCANS",          3))   # min scans a stock must appear in


def load(data_file: str) -> dict:
    if not os.path.exists(data_file):
        os.makedirs(os.path.dirname(data_file), exist_ok=True)
        return {
            "positions": [],
            "settings": {
                "sl": SL_PCT, "tgt": TGT_PCT,
                "posSize": POS_SIZE, "maxPos": MAX_POS,
                "minScans": MIN_SCANS,
            },
            "equity_curve": []
        }
    with open(data_file) as f:
        d = json.load(f)
    if "equity_curve" not in d:
        d["equity_curve"] = []
    if "minScans" not in d.get("settings", {}):
        d["settings"]["minScans"] = MIN_SCANS
    return d


def save(data: dict, data_file: str):
    os.makedirs(os.path.dirname(data_file), exist_ok=True)
    with open(data_file, "w") as f:
        json.dump(data, f, indent=2)


def check_exits(data: dict, prices: dict) -> list:
    closed = []
    for p in data["positions"]:
        if p["status"] != "open":
            continue
        px = prices.get(p["symbol"])
        if not px:
            continue
        p["currentPrice"] = round(px, 2)
        if px <= p["sl"]:       reason = "SL hit"
        elif px >= p["tgt"]:    reason = "Target hit"
        else:                   continue
        p.update({
            "status": "closed", "exitPrice": round(px, 2),
            "exitDate": datetime.date.today().isoformat(), "exitReason": reason,
            "pnl":    round((px - p["entryPrice"]) * p["qty"], 2),
            "pnlPct": round((px - p["entryPrice"]) / p["entryPrice"] * 100, 2),
        })
        closed.append(p)
        log.info("CLOSED %-12s @ Rs%-8.2f (%s) PnL Rs%+.0f (%+.2f%%)",
                 p["symbol"], px, reason, p["pnl"], p["pnlPct"])
    return closed


def enter_trades(data: dict, scan_results: dict, prices: dict, scan_date: str) -> list:
    s         = data["settings"]
    min_scans = s.get("minScans", MIN_SCANS)
    n_open    = sum(1 for p in data["positions"] if p["status"] == "open")
    already   = {p["symbol"] for p in data["positions"] if p["status"] == "open"}

    # Build symbol -> scan list map
    seen: dict = {}
    for sid, syms in scan_results.items():
        for sym in syms:
            seen.setdefault(sym, []).append(sid)

    # Filter: only stocks appearing in min_scans or more
    qualified = {sym: sids for sym, sids in seen.items() if len(sids) >= min_scans}
    log.info("  %d symbols qualified (%d+ scans): %s",
             len(qualified), min_scans,
             ", ".join(qualified.keys()) if qualified else "none")

    new = []
    for sym, sids in qualified.items():
        if sym in already:
            log.info("  SKIP %-12s already in portfolio", sym)
            continue
        if n_open >= s["maxPos"]:
            log.info("  Max positions (%d) reached.", s["maxPos"])
            break
        px = prices.get(sym)
        if not px:
            log.warning("  No price for %s — skipping.", sym)
            continue
        qty = int(s["posSize"] / px)
        if qty < 1:
            continue
        t = {
            "id": f"{int(time.time())}_{sym}", "symbol": sym, "scans": sids,
            "scanDate": scan_date, "entryDate": datetime.date.today().isoformat(),
            "entryPrice": round(px, 2), "currentPrice": round(px, 2),
            "sl":  round(px * (1 - s["sl"]  / 100), 2),
            "tgt": round(px * (1 + s["tgt"] / 100), 2),
            "qty": qty, "invested": round(px * qty, 2), "status": "open",
            "exitPrice": None, "exitDate": None, "exitReason": None,
            "pnl": None, "pnlPct": None,
        }
        data["positions"].append(t)
        new.append(t)
        n_open += 1
        log.info("  ENTERED %-12s @ Rs%-8.2f SL:Rs%.2f TGT:Rs%.2f Qty:%d Scans(%d):%s",
                 sym, px, t["sl"], t["tgt"], qty, len(sids), ",".join(sids))
    return new


def update_equity_curve(data: dict):
    closed = [p for p in data["positions"] if p["status"] == "closed"]
    total  = round(sum(p["pnl"] for p in closed if p.get("pnl")), 2)
    today  = datetime.date.today().isoformat()
    curve  = data.setdefault("equity_curve", [])
    if curve and curve[-1]["date"] == today:
        curve[-1]["pnl"] = total
    else:
        curve.append({"date": today, "pnl": total})
