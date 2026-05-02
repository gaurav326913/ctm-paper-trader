"""
dashboard.py
Generates a self-contained HTML dashboard from trades.json.
Written to docs/index.html which GitHub Pages serves automatically.
"""

import json, os, datetime

SCANS_META = {
    "champion-d":  {"label": "Champion Daily",   "color": "#3B82F6"},
    "champion-w":  {"label": "Champion Weekly",  "color": "#8B5CF6"},
    "contraction": {"label": "Contraction",      "color": "#10B981"},
    "ppc":         {"label": "PPC",              "color": "#F59E0B"},
    "npc":         {"label": "NPC",              "color": "#EF4444"},
    "bigmover":    {"label": "Big Movers",       "color": "#EC4899"},
    "indstrong":   {"label": "India Strong",     "color": "#14B8A6"},
    "newstock":    {"label": "New Stocks (IPO)", "color": "#6B7280"},
}

G, R = "#10B981", "#EF4444"


def _clr(v): return G if v >= 0 else R


def generate(data: dict, scan_results: dict) -> str:
    pos    = data.get("positions", [])
    cl     = [p for p in pos if p["status"] == "closed"]
    op     = [p for p in pos if p["status"] == "open"]
    wins   = [p for p in cl if (p.get("pnl") or 0) > 0]
    losses = [p for p in cl if (p.get("pnl") or 0) <= 0]
    rpnl   = sum(p["pnl"] for p in cl if p.get("pnl"))
    unr    = sum((p.get("currentPrice", p["entryPrice"]) - p["entryPrice"]) * p["qty"] for p in op)
    wr     = len(wins) / len(cl) * 100 if cl else 0
    ag     = sum(p["pnlPct"] for p in wins) / len(wins) if wins else 0
    al     = sum(p["pnlPct"] for p in losses) / len(losses) if losses else 0
    total_invested = sum(p["invested"] for p in op)
    today  = datetime.date.today().strftime("%d %b %Y")
    updated = datetime.datetime.now().strftime("%d %b %Y, %H:%M IST")

    # ── Equity curve data ──────────────────────────────────────────────────────
    curve = data.get("equity_curve", [])
    curve_labels = json.dumps([c["date"] for c in curve])
    curve_values = json.dumps([c["pnl"]  for c in curve])

    # ── Scan performance data ──────────────────────────────────────────────────
    scan_stats = {}
    for sid in SCANS_META:
        trades = [p for p in cl if sid in p.get("scans", [])]
        w = [p for p in trades if (p.get("pnl") or 0) > 0]
        scan_stats[sid] = {
            "count": len(trades),
            "winRate": round(len(w) / len(trades) * 100, 1) if trades else 0,
            "avgPnl": round(sum(p["pnlPct"] for p in trades) / len(trades), 2) if trades else 0,
        }

    scan_perf_labels = json.dumps([SCANS_META[s]["label"] for s in SCANS_META])
    scan_perf_wr     = json.dumps([scan_stats[s]["winRate"] for s in SCANS_META])
    scan_perf_avg    = json.dumps([scan_stats[s]["avgPnl"] for s in SCANS_META])
    scan_perf_colors = json.dumps([SCANS_META[s]["color"] for s in SCANS_META])

    # ── Open positions rows ────────────────────────────────────────────────────
    def scan_badge(sid):
        m = SCANS_META.get(sid, {"label": sid, "color": "#6B7280"})
        return (f'<span style="background:{m["color"]}22;color:{m["color"]};'
                f'padding:2px 7px;border-radius:4px;font-size:11px;font-weight:600">'
                f'{m["label"]}</span>')

    op_rows = ""
    for p in sorted(op, key=lambda x: x["entryDate"], reverse=True):
        cur  = p.get("currentPrice", p["entryPrice"])
        unr1 = (cur - p["entryPrice"]) * p["qty"]
        pct  = (cur - p["entryPrice"]) / p["entryPrice"] * 100
        days = (datetime.date.today() - datetime.date.fromisoformat(p["entryDate"])).days
        sl_pct_away  = (p["sl"]  - cur) / cur * 100
        tgt_pct_away = (p["tgt"] - cur) / cur * 100
        op_rows += f"""<tr class="trow">
          <td><b>{p["symbol"]}</b><br><span class="muted">{days}d held</span></td>
          <td>{"".join(scan_badge(s) for s in p["scans"])}</td>
          <td>Rs{p["entryPrice"]:,.2f}</td>
          <td>Rs{cur:,.2f}</td>
          <td style="color:{_clr(unr1)}"><b>Rs{unr1:+,.0f}</b><br><span style="font-size:11px">{pct:+.2f}%</span></td>
          <td style="color:{R}">Rs{p["sl"]:,.2f}<br><span class="muted" style="font-size:10px">{sl_pct_away:.1f}% away</span></td>
          <td style="color:{G}">Rs{p["tgt"]:,.2f}<br><span class="muted" style="font-size:10px">{tgt_pct_away:.1f}% away</span></td>
          <td>{p["entryDate"]}</td>
        </tr>"""

    # ── Closed trades rows (last 30) ───────────────────────────────────────────
    cl_rows = ""
    for p in sorted(cl, key=lambda x: x.get("exitDate",""), reverse=True)[:30]:
        cl_rows += f"""<tr class="trow">
          <td><b>{p["symbol"]}</b></td>
          <td>{"".join(scan_badge(s) for s in p["scans"])}</td>
          <td>{p["entryDate"]}</td>
          <td>{p.get("exitDate","")}</td>
          <td>Rs{p["entryPrice"]:,.2f}</td>
          <td>Rs{p.get("exitPrice",0):,.2f}</td>
          <td style="color:{_clr(p.get('pnl',0))}"><b>Rs{p.get('pnl',0):+,.0f}</b></td>
          <td style="color:{_clr(p.get('pnlPct',0))}"><b>{p.get('pnlPct',0):+.2f}%</b></td>
          <td><span style="background:{'#FEF3C7' if 'Target' in p.get('exitReason','') else '#FEE2E2'};
               color:{'#92400E' if 'Target' in p.get('exitReason','') else '#991B1B'};
               padding:2px 8px;border-radius:4px;font-size:11px">{p.get("exitReason","")}</span></td>
        </tr>"""

    # ── Today's scan results ───────────────────────────────────────────────────
    scan_rows = ""
    for sid, cfg in SCANS_META.items():
        syms = scan_results.get(sid, [])
        scan_rows += f"""<tr class="trow">
          <td>{scan_badge(sid)}</td>
          <td><b>{len(syms)}</b></td>
          <td style="font-size:12px;color:#6B7280">{", ".join(syms[:12])}{"..." if len(syms)>12 else ""}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CTM Paper Trader</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0F172A;color:#E2E8F0;font-size:14px}}
  .header{{background:#1E293B;border-bottom:1px solid #334155;padding:16px 24px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px}}
  .header h1{{font-size:20px;font-weight:700;color:#F1F5F9}}
  .updated{{font-size:12px;color:#64748B}}
  .container{{max-width:1400px;margin:0 auto;padding:20px 16px}}
  .metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin-bottom:24px}}
  .metric{{background:#1E293B;border:1px solid #334155;border-radius:12px;padding:16px}}
  .metric-label{{font-size:11px;color:#64748B;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px}}
  .metric-value{{font-size:24px;font-weight:700;color:#F1F5F9}}
  .metric-value.pos{{color:#10B981}}
  .metric-value.neg{{color:#EF4444}}
  .charts{{display:grid;grid-template-columns:2fr 1fr;gap:16px;margin-bottom:24px}}
  .card{{background:#1E293B;border:1px solid #334155;border-radius:12px;padding:20px}}
  .card-title{{font-size:13px;font-weight:600;color:#94A3B8;text-transform:uppercase;letter-spacing:.05em;margin-bottom:16px}}
  .tabs{{display:flex;gap:4px;margin-bottom:20px;border-bottom:1px solid #334155;padding-bottom:0}}
  .tab{{padding:8px 16px;font-size:13px;cursor:pointer;border:none;background:none;color:#64748B;border-bottom:2px solid transparent;margin-bottom:-1px;transition:all .15s}}
  .tab.active{{color:#38BDF8;border-bottom-color:#38BDF8}}
  .tab-content{{display:none}}
  .tab-content.active{{display:block}}
  .table-wrap{{overflow-x:auto}}
  table{{width:100%;border-collapse:collapse;font-size:13px}}
  th{{text-align:left;padding:10px 12px;color:#64748B;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.04em;border-bottom:1px solid #334155}}
  .trow td{{padding:10px 12px;border-bottom:1px solid #1E293B;vertical-align:middle}}
  .trow:hover td{{background:#334155}}
  .muted{{color:#64748B}}
  .empty{{text-align:center;padding:40px;color:#475569}}
  @media(max-width:768px){{
    .charts{{grid-template-columns:1fr}}
    .metrics{{grid-template-columns:repeat(2,1fr)}}
  }}
</style>
</head>
<body>

<div class="header">
  <h1>CTM Paper Trader</h1>
  <div class="updated">Last updated: {updated}</div>
</div>

<div class="container">

  <!-- Metrics -->
  <div class="metrics">
    <div class="metric"><div class="metric-label">Total Trades</div><div class="metric-value">{len(cl)+len(op)}</div></div>
    <div class="metric"><div class="metric-label">Open Positions</div><div class="metric-value">{len(op)}</div></div>
    <div class="metric"><div class="metric-label">Win Rate</div><div class="metric-value {'pos' if wr>=50 else 'neg'}">{wr:.1f}%</div></div>
    <div class="metric"><div class="metric-label">Realized P&L</div><div class="metric-value {'pos' if rpnl>=0 else 'neg'}">Rs{rpnl:+,.0f}</div></div>
    <div class="metric"><div class="metric-label">Unrealized P&L</div><div class="metric-value {'pos' if unr>=0 else 'neg'}">Rs{unr:+,.0f}</div></div>
    <div class="metric"><div class="metric-label">Capital Deployed</div><div class="metric-value">Rs{total_invested:,.0f}</div></div>
    <div class="metric"><div class="metric-label">Avg Gain</div><div class="metric-value pos">{ag:+.1f}%</div></div>
    <div class="metric"><div class="metric-label">Avg Loss</div><div class="metric-value neg">{al:.1f}%</div></div>
  </div>

  <!-- Charts -->
  <div class="charts">
    <div class="card">
      <div class="card-title">Equity Curve (Realized P&L)</div>
      <canvas id="equityChart" height="120"></canvas>
    </div>
    <div class="card">
      <div class="card-title">Win Rate by Scan</div>
      <canvas id="scanChart" height="120"></canvas>
    </div>
  </div>

  <!-- Tabs -->
  <div class="tabs">
    <button class="tab active" onclick="showTab('open')">Open Positions ({len(op)})</button>
    <button class="tab" onclick="showTab('closed')">Trade History ({len(cl)})</button>
    <button class="tab" onclick="showTab('scans')">Today's Scans</button>
  </div>

  <div id="tab-open" class="tab-content active">
    <div class="table-wrap">
      {'<table><thead><tr><th>Symbol</th><th>Scans</th><th>Entry</th><th>Current</th><th>Unrealized</th><th>Stop Loss</th><th>Target</th><th>Since</th></tr></thead><tbody>' + op_rows + '</tbody></table>' if op else '<div class="empty">No open positions yet.</div>'}
    </div>
  </div>

  <div id="tab-closed" class="tab-content">
    <div class="table-wrap">
      {'<table><thead><tr><th>Symbol</th><th>Scans</th><th>Entry Date</th><th>Exit Date</th><th>Entry Rs</th><th>Exit Rs</th><th>P&L Rs</th><th>P&L %</th><th>Reason</th></tr></thead><tbody>' + cl_rows + '</tbody></table>' if cl else '<div class="empty">No closed trades yet.</div>'}
    </div>
  </div>

  <div id="tab-scans" class="tab-content">
    <div class="table-wrap">
      <table><thead><tr><th>Scan</th><th>Stocks Found</th><th>Symbols</th></tr></thead>
      <tbody>{scan_rows}</tbody></table>
    </div>
  </div>

</div>

<script>
function showTab(name) {{
  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  event.target.classList.add('active');
}}

const chartDefaults = {{
  responsive: true,
  plugins: {{ legend: {{ display: false }} }},
  scales: {{
    x: {{ ticks: {{ color: '#64748B', font: {{ size: 10 }} }}, grid: {{ color: '#1E293B' }} }},
    y: {{ ticks: {{ color: '#64748B', font: {{ size: 10 }} }}, grid: {{ color: '#334155' }} }}
  }}
}};

// Equity curve
const eLabels = {curve_labels};
const eValues = {curve_values};
if (eLabels.length > 0) {{
  new Chart(document.getElementById('equityChart'), {{
    type: 'line',
    data: {{
      labels: eLabels,
      datasets: [{{
        data: eValues,
        borderColor: eValues[eValues.length-1] >= 0 ? '#10B981' : '#EF4444',
        backgroundColor: eValues[eValues.length-1] >= 0 ? '#10B98120' : '#EF444420',
        fill: true, tension: 0.3, pointRadius: 3,
      }}]
    }},
    options: {{ ...chartDefaults }}
  }});
}} else {{
  document.getElementById('equityChart').parentElement.innerHTML +=
    '<p style="color:#475569;text-align:center;margin-top:20px">No closed trades yet — equity curve will appear here.</p>';
}}

// Scan win rate
const sLabels = {scan_perf_labels};
const sWr     = {scan_perf_wr};
const sColors = {scan_perf_colors};
new Chart(document.getElementById('scanChart'), {{
  type: 'bar',
  data: {{
    labels: sLabels,
    datasets: [{{ data: sWr, backgroundColor: sColors.map(c => c + '99'), borderColor: sColors, borderWidth: 1 }}]
  }},
  options: {{
    ...chartDefaults,
    plugins: {{ legend: {{ display: false }}, tooltip: {{
      callbacks: {{ label: ctx => ' Win rate: ' + ctx.parsed.y + '%' }}
    }} }},
    scales: {{
      x: {{ ticks: {{ color: '#64748B', font: {{ size: 9 }}, maxRotation: 45 }}, grid: {{ color: '#1E293B' }} }},
      y: {{ min: 0, max: 100, ticks: {{ color: '#64748B', callback: v => v + '%' }}, grid: {{ color: '#334155' }} }}
    }}
  }}
}});
</script>
</body>
</html>"""
    return html


def write(data: dict, scan_results: dict, output_path: str):
    html = generate(data, scan_results)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
