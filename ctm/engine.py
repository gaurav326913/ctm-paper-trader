"""
engine.py
Paper trade engine with:
  - Pending queue: stocks identified at 6 PM, entered next morning at open
  - ATR-based SL (2x ATR) and Target (4x ATR)
  - Swing-trading scan qualification rules

QUALIFICATION LOGIC (final v3, June 2026):

Philosophy: Champion Daily is the anchor. NOTHING qualifies without it.
This ensures every pick has confirmed daily momentum PLUS at least one
additional signal. (v2 had a loophole: Tier 2 {ppc, indstrong} bypassed
the anchor entirely — removed in v3, same failure mode as the old
170-candidate standalone-Champion-Weekly bug, just relocated.)

Champion Weekly alone removed from Tier 2 — was letting 170 stocks
through on strong market days. Weekly is now only used in combo
with Daily (Tier 1), where it's the highest-conviction setup.

Within the position cap, candidates are prioritized by signal count
(more confirming scans = queued first) rather than arbitrary dict order.

Expected output:
  Strong bull day   : 20-60 candidates (capped at MAX_POSITIONS=20)
  Normal day        : 5-20 candidates
  Choppy/weak day   : 0-5 candidates
  Below 200 DMA     : 0-3 candidates (Tier 1 only)
"""

import json, os, time, datetime, logging

log = logging.getLogger("ctm.engine")

POS_SIZE   = int(os.environ.get("POSITION_SIZE", 25000))
MAX_POS    = int(os.environ.get("MAX_POSITIONS",    20))
ATR_SL     = float(os.environ.get("ATR_SL_MULT",   2.0))
ATR_TGT    = float(os.environ.get("ATR_TGT_MULT",  4.0))
FB_SL_PCT  = 5.0
FB_TGT_PCT = 10.0


# ── Qualification rules ───────────────────────────────────────────────────────

# Tier 1: queue regardless of Nifty health
# All combos require Champion Daily — ensures confirmed daily momentum.
# Champion Weekly + Daily is the single best swing setup available.
TIER1_COMBOS = [
    {"champion-w", "champion-d"},   # both timeframes confirmed — best possible
    {"champion-d", "contraction"},  # uptrend + coiling near highs
    {"champion-d", "ppc"},          # uptrend + institutional volume surge
    {"champion-d", "indstrong"},    # quality large-cap in confirmed uptrend
]

# Tier 2: queue only when Nifty healthy (above 200 DMA)
# Still anchored to Champion Daily — only the SECOND confirming signal
# changes vs Tier 1. {ppc, indstrong} removed: it had no champion-d
# requirement at all and could spike candidate count on high-volume
# rally days (same root cause as the old champion-w standalone bug).
TIER2_COMBOS = [
    {"champion-d", "bigmover"},     # daily trend + 6-month breakout level
]

# Never queue standalone:
#   champion-d alone  — anchor scan, needs confirmation
#   champion-w alone  — too broad standalone (moved to Tier 1 combo only)
#   contraction alone — coiling without daily trend confirmation
#   bigmover alone    — noise, no trend filter
#   indstrong alone   — quality screener, not an entry trigger
#   ppc + indstrong (no champion-d) — institutional volume without
#       confirmed trend; removed in v3, see TIER2 comment above
#   npc               — exit alert on open positions only
#   newstock          — IPOs lack ATR history


def _qualifies(scans_set: set, market_healthy: bool) -> bool:
    for combo in TIER1_COMBOS:
        if combo.issubset(scans_set):
            return True
    if market_healthy:
        for combo in TIER2_COMBOS:
            if combo.issubset(scans_set):
                return True
    return False


def qualified_candidates(data: dict, scan_results: dict, market_healthy: bool) -> dict:
    """Return {symbol: scan_ids} for candidates that pass entry rules."""
    already_open    = {p["symbol"] for p in data["positions"] if p["status"] == "open"}
    already_pending = {p["symbol"] for p in data.get("pending", [])}

    seen: dict = {}
    for sid, syms in scan_results.items():
        for sym in syms:
            seen.setdefault(sym, set()).add(sid)

    return {
        sym: sids for sym, sids in seen.items()
        if _qualifies(sids, market_healthy)
        and sym not in already_open
        and sym not in already_pending
        and ("npc" not in sids or len(sids) > 1)  # currently a no-op: no combo
                                                    # is satisfied by npc alone,
                                                    # kept as a documented guard
    }


def load(data_file: str) -> dict:
    if not os.path.exists(data_file):
        os.makedirs(os.path.dirname(data_file), exist_ok=True)
        return _empty()
    with open(data_file) as f:
        d = json.load(f)
    for k, v in _empty().items():
        if k not in d:
            d[k] = v
    return d


def save(data: dict, data_file: str):
    os.makedirs(os.path.dirname(data_file), exist_ok=True)
    with open(data_file, "w") as f:
        json.dump(data, f, indent=2)


def _empty() -> dict:
    return {
        "positions":    [],
        "pending":      [],
        "equity_curve": [],
        "settings": {
            "posSize":  POS_SIZE,
            "maxPos":   MAX_POS,
            "atrSL":    ATR_SL,
            "atrTgt":   ATR_TGT,
        },
    }


# ── Evening job (6 PM): queue candidates ─────────────────────────────────────

def queue_candidates(data: dict, scan_results: dict, scan_date: str,
                     market_healthy: bool) -> list:
    s            = data["settings"]
    already_open = {p["symbol"] for p in data["positions"] if p["status"] == "open"}

    # NPC: exit alert on open positions
    npc_syms = set(scan_results.get("npc", []))
    npc_open = npc_syms & already_open
    if npc_open:
        log.warning("NPC alert (high-volume down day) on open positions — review exits: %s",
                    ", ".join(sorted(npc_open)))

    qualified = qualified_candidates(data, scan_results, market_healthy)

    if not market_healthy:
        log.info("Market unhealthy (Nifty below 200 DMA) — only Tier 1 setups qualify.")

    log.info("Candidates qualified: %d stocks — %s",
             len(qualified),
             ", ".join(
                 f"{sym}({','.join(sorted(sids))})"
                 for sym, sids in qualified.items()
             ) if qualified else "none")

    # Prioritize by signal strength (more confirming scans first) so the
    # best setups get queued before hitting the position cap on busy days.
    ranked = sorted(qualified.items(), key=lambda kv: len(kv[1]), reverse=True)

    queued = []
    for sym, sids in ranked:
        n_open = sum(1 for p in data["positions"] if p["status"] == "open")
        if n_open + len(data.get("pending", [])) >= s["maxPos"]:
            log.info("Position limit reached (%d) — not queuing more.", s["maxPos"])
            break
        entry = {
            "symbol":   sym,
            "scans":    sorted(sids),
            "scanDate": scan_date,
            "queuedAt": datetime.datetime.now().isoformat(),
        }
        data.setdefault("pending", []).append(entry)
        queued.append(sym)
        log.info("  QUEUED %-12s (scans: %s)", sym, ", ".join(sorted(sids)))

    return queued


# ── Morning job (9:20 AM): enter pending at open price ───────────────────────

def enter_pending(data: dict, open_prices: dict, atrs: dict) -> list:
    s        = data["settings"]
    pending  = data.get("pending", [])
    if not pending:
        log.info("No pending trades to enter.")
        return []

    entered       = []
    still_pending = []

    for item in pending:
        sym = item["symbol"]
        px  = open_prices.get(sym)
        if not px:
            log.warning("No open price for %s — keeping in queue for tomorrow.", sym)
            still_pending.append(item)
            continue

        atr = atrs.get(sym)
        if atr:
            sl      = round(px - ATR_SL  * atr, 2)
            tgt     = round(px + ATR_TGT * atr, 2)
            sl_pct  = round((px - sl)  / px * 100, 2)
            tgt_pct = round((tgt - px) / px * 100, 2)
            log.info("  ATR=%.2f  SL=%.1f%% below  TGT=%.1f%% above", atr, sl_pct, tgt_pct)
        else:
            sl  = round(px * (1 - FB_SL_PCT  / 100), 2)
            tgt = round(px * (1 + FB_TGT_PCT / 100), 2)
            log.warning("  No ATR for %s — using fixed SL/TGT", sym)

        if sl >= px or tgt <= px:
            log.warning("  Invalid SL/TGT for %s — skipping", sym)
            continue

        qty = int(s["posSize"] / px)
        if qty < 1:
            log.warning("  Position size too small for %s at Rs%.2f — skipping", sym, px)
            continue

        trade = {
            "id":           f"{int(time.time())}_{sym}",
            "symbol":       sym,
            "scans":        item["scans"],
            "scanDate":     item["scanDate"],
            "entryDate":    datetime.date.today().isoformat(),
            "entryType":    "open",
            "entryPrice":   round(px, 2),
            "currentPrice": round(px, 2),
            "atr":          atr,
            "sl":           sl,
            "tgt":          tgt,
            "qty":          qty,
            "invested":     round(px * qty, 2),
            "status":       "open",
            "exitPrice":    None,
            "exitDate":     None,
            "exitReason":   None,
            "pnl":          None,
            "pnlPct":       None,
        }
        data["positions"].append(trade)
        entered.append(trade)
        log.info("  ENTERED %-12s @ Rs%.2f  SL:Rs%.2f  TGT:Rs%.2f  ATR:%.2f  Qty:%d",
                 sym, px, sl, tgt, atr or 0, qty)

    data["pending"] = still_pending
    return entered


# ── Evening: update current prices on open positions ─────────────────────────

def update_prices(data: dict, prices: dict):
    for p in data["positions"]:
        if p["status"] != "open":
            continue
        px = prices.get(p["symbol"])
        if px:
            p["currentPrice"] = round(px, 2)


# ── Check SL / Target exits ───────────────────────────────────────────────────

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
            "status":     "closed",
            "exitPrice":  round(px, 2),
            "exitDate":   datetime.date.today().isoformat(),
            "exitReason": reason,
            "pnl":        round((px - p["entryPrice"]) * p["qty"], 2),
            "pnlPct":     round((px - p["entryPrice"]) / p["entryPrice"] * 100, 2),
        })
        closed.append(p)
        log.info("CLOSED %-12s @ Rs%.2f (%s) PnL Rs%+.0f (%+.2f%%)",
                 p["symbol"], px, reason, p["pnl"], p["pnlPct"])
    return closed


# ── Equity curve ──────────────────────────────────────────────────────────────

def update_equity_curve(data: dict):
    closed = [p for p in data["positions"] if p["status"] == "closed"]
    total  = round(sum(p["pnl"] for p in closed if p.get("pnl")), 2)
    today  = datetime.date.today().isoformat()
    curve  = data.setdefault("equity_curve", [])
    if curve and curve[-1]["date"] == today:
        curve[-1]["pnl"] = total
    else:
        curve.append({"date": today, "pnl": total})
