# CTM Paper Trader

Automated paper trading system. Runs every weekday at 6 PM IST.
Live dashboard viewable from any browser — office laptop, home, mobile.

---

## Setup (one time, ~15 minutes on your personal laptop)

### 1. Create a private GitHub repository

- Go to github.com, sign in, click New repository
- Name: ctm-paper-trader, set to Private
- Upload all files from this zip maintaining folder structure

### 2. Add GitHub Secrets

Settings > Secrets and variables > Actions > New repository secret

  CHARTINK_EMAIL      your Chartink login email
  CHARTINK_PASSWORD   your Chartink password

That is all. No Kite, no Groww, no API keys. Prices come from NSE public data.

### 3. Enable GitHub Pages

Settings > Pages > Source: Deploy from a branch > Branch: main > Folder: /docs > Save

Your dashboard URL will be:
  https://YOUR-GITHUB-USERNAME.github.io/ctm-paper-trader/

Bookmark this. Open it from anywhere.

### 4. Test

Actions > CTM Daily Scan > Run workflow > Run workflow

Takes 3-5 minutes. Then open your dashboard URL — it will show today's scan results.

---

## Daily experience

- 6:15 PM IST: open your dashboard URL to see what happened
- Nothing else required

Manual run anytime: Actions > CTM Daily Scan > Run workflow

---

## Adjusting settings

Edit data/trades.json on GitHub (click file > pencil icon):

  "settings": {
    "sl": 5.0,        stop loss %
    "tgt": 15.0,      target %
    "posSize": 25000  Rs per simulated trade
    "maxPos": 20      max concurrent positions
  }

---

## Troubleshooting

CSRF token not found: Chartink temporarily down. Next run will work.
No scan results: Check CHARTINK_EMAIL and CHARTINK_PASSWORD secrets.
Dashboard not loading: Make sure GitHub Pages is enabled (Step 3).
