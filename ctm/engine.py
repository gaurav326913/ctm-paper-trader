"""engine.py — paper trade entry, exit, and persistence."""

import json, os, time, datetime, logging

log = logging.getLogger("ctm.engine")

SL_PCT   = float(os.environ.get("STOP_LOSS_PCT",  5.0))
TGT_PCT  = float(os.environ.get("TARGET_PCT",    15.0))
POS_SIZE = int(os.environ.get("POSITION_SIZE",  25000))
MAX_POS  = int(os.environ.get("MAX_POSITIONS",     20))

DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "trades.json")


def load() -> dict:
    if not os.path.exists(DATA_FILE):
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        return {"positions": [], "settings": {"sl": SL_PCT, "tgt": TGT_PCT, "posSize": POS_SIZE, "maxPos": MAX_POS}, "equity_curve": []}
    with open(DATA_FILE) as f:
        d = json.load(f)
    if "equity_curve" not in d:
        d["equity_curve"] = []
    return d


def save(data: dict):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w") as f:
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
    s       = data["settings"]
    n_open  = sum(1 for p in data["positions"] if p["status"] == "open")
    already = {p["symbol"] for p in data["positions"] if p["status"] == "open"}
    seen    = {}
    for sid, syms in scan_results.items():
        for sym in syms:
            seen.setdefault(sym, []).append(sid)
    new = []
    for sym, sids in seen.items():
        if sym in already or n_open >= s["maxPos"]: continue
        px = prices.get(sym)
        if not px: continue
        qty = int(s["posSize"] / px)
        if qty < 1: continue
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
        log.info("ENTERED %-12s @ Rs%-8.2f SL:Rs%-8.2f TGT:Rs%-8.2f Qty:%d Scans:%s",
                 sym, px, t["sl"], t["tgt"], qty, ",".join(sids))
    return new


def update_equity_curve(data: dict):
    """Append today's realized P&L snapshot to the equity curve."""
    closed = [p for p in data["positions"] if p["status"] == "closed"]
    total  = round(sum(p["pnl"] for p in closed if p.get("pnl")), 2)
    today  = datetime.date.today().isoformat()
    curve  = data.setdefault("equity_curve", [])
    # Only one entry per day
    if curve and curve[-1]["date"] == today:
        curve[-1]["pnl"] = total
    else:
        curve.append({"date": today, "pnl": total})
