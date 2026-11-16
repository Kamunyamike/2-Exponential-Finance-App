# 2 Exponential Finance App

## USD Money Doubling Tracker

A personal financial dashboard for a simple compounding challenge: start with **$10** and try to **double it every week**.

The app projects where you should be each week, lets you record what you actually have, and shows whether you are ahead of or behind the plan.

```
Aₙ = P × mⁿ
P = initial capital ($10 by default)
m = weekly multiplication factor (2 by default)
n = number of completed weeks
```

| Week | 0 | 1 | 2 | 3 | 4 | 5 |
|------|---|---|---|---|---|---|
| Balance | $10 | $20 | $40 | $80 | $160 | $320 |

---

## Features

| Section | What it does |
|---|---|
| **Dashboard** | Four KPI cards (initial capital, current week, projected balance, total growth), growth curve, milestone weeks ($1K / $1M / $1B), and a snapshot of your real progress |
| **Week Calculator** | Enter any week (0–520) to see the projected amount, previous week's amount, required weekly gain, total increase and % growth |
| **Growth Table** | Every week from the start to the selected week: Opening Balance, Weekly Target (gain needed that week), Closing Balance, Growth (cumulative %). Download as CSV |
| **Growth Chart** | Interactive Plotly chart with the starting capital and selected week highlighted, an adjustable range and a log-scale toggle |
| **Actual Tracking** | Record, edit or delete your real end-of-week balance (with optional note). Compares projected vs actual, the difference and % achievement. CSV export, backup and restore |
| **Progress** | Current achievement %, weeks completed, total capital growth, weeks ahead/behind target, actual-vs-projected chart and weekly achievement bars |

**Sidebar:** navigation plus challenge settings: initial capital, weekly multiplier, selected week, and a one-click reset to $10 × 2. Settings are saved along with your balances.

### How the numbers are calculated

- Nothing is hard-coded. Every value is calculated from `P × mⁿ`.
- Calculations use Python's exact arithmetic (`int` / `fractions.Fraction`). For the default challenge this is pure integer maths, so even week 520 (`10 × 2⁵²⁰`, 158 digits) is exact.
- Amounts are rounded to cents (half-up) only for display and export.
- **Large numbers:** KPI cards abbreviate ($10.74B). Amounts with more than 21 digits use scientific notation ($3.43 × 10^157). The Week Calculator can show the full exact value. The chart leaves out any week beyond the largest number a float can hold (~1.8 × 10³⁰⁸) and tells you so.
- **"Weeks ahead/behind"** finds the point on the plan your balance matches, e.g. $85 at week 3 equals the plan's week 3.09, so you are 0.09 weeks ahead.

### Input validation

- Week: whole number from 0 to 520. Negative numbers are rejected.
- Initial capital: $0.01 to $1,000,000,000.
- Multiplier: 1.01 to 10.
- Actual balance: zero or more. Accepts `1250.5`, `$1,250.50` and `1,250.50`. Text that isn't a number shows an error.
- Database and drawing errors appear as a friendly message instead of crashing the app.

---

## Project structure

```
.
├── app.py                 # Streamlit UI: layout, pages, charts, styling
├── calculations.py        # Business logic: formula, validation, formatting (no Streamlit)
├── database.py            # Persistence: SQLite by default, PostgreSQL via DATABASE_URL
├── requirements.txt
├── README.md
├── .gitignore
├── .streamlit/
│   └── config.toml        # Dark navy / green theme
└── tests/
    └── test_calculations.py
```

---

## Run locally

You need Python 3.10 or newer.

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
# macOS / Linux:
source .venv/bin/activate
# Windows (PowerShell):
.venv\Scripts\Activate.ps1

# 2. Install dependencies
pip install -r requirements.txt

# 3. (Optional) run the tests
python -m pytest -q

# 4. Start the app
streamlit run app.py
```

The app opens at <http://localhost:8501>. Your balances are saved in `data/tracker.db`, which stays on your computer between runs.

---

## ⚠️ Data persistence on Streamlit Community Cloud: read this first

**Streamlit Community Cloud does not keep files you write.** The app runs in a container. Its disk is wiped whenever the app restarts, goes to sleep from inactivity, is redeployed (every push to GitHub), or the platform moves it. A SQLite file on that disk will eventually lose your data.

The app handles this in two ways:

### Option A: Free hosted PostgreSQL (recommended for permanent storage)

`database.py` uses SQLAlchemy, so the same code runs on SQLite or PostgreSQL. Set one secret called `DATABASE_URL` and the app switches automatically. No code changes are needed.

Free PostgreSQL tiers that need no credit card at the time of writing include **Neon** (neon.tech) and **Supabase** (supabase.com). Check their current terms. Neither needs an API key, only the database connection string.

1. Create a free account and a new project/database.
2. Copy the **connection string**. It looks like
   `postgresql://user:password@host:5432/dbname?sslmode=require`
   (on Supabase use the *Session pooler* string, which works over IPv4).
3. Add it as a secret (see step 4 of the Cloud deployment below):
   ```toml
   DATABASE_URL = "postgresql://user:password@host:5432/dbname?sslmode=require"
   ```
4. Reboot the app. The sidebar footer changes to **🟢 Storage: External postgresql database**. The tables are created automatically.

To use the same database locally, create `.streamlit/secrets.toml` with the same line, or set the `DATABASE_URL` environment variable. `secrets.toml` is in `.gitignore` so your password never goes to GitHub.

### Option B: SQLite + CSV backup (zero setup)

If you don't set `DATABASE_URL`, the app uses SQLite. The sidebar shows **🟡 Storage: Local SQLite file**. On the Cloud, use **Actual Tracking → 💾 Backup, restore & storage**:

- **Download backup CSV** after you record a week.
- **Restore from backup CSV** if the app restarts with no data.

This is fine for occasional use, but Option A is the real fix.

---

## Deploy: step by step

### Deploy on Streamlit Community Cloud

1. Go to <https://share.streamlit.io> and **sign in with GitHub**. Authorise access to your repositories.
2. Click **Create app** → **Deploy a public app from GitHub** (wording may vary slightly).
3. Fill in:
   - **Repository:** `Kamunyamike/2-Exponential-Finance-App`
   - **Branch:** `main`
   - **Main file path:** `app.py`
   - **App URL:** choose a subdomain (optional)
4. **(Recommended) Add your database secret:** open **Advanced settings**, pick a Python version (3.11 or 3.12 are good choices), and paste into **Secrets**:
   ```toml
   DATABASE_URL = "postgresql://user:password@host:5432/dbname?sslmode=require"
   ```
   You can also add or change this later under **App → Settings → Secrets**.
5. Click **Deploy**. The first build takes a few minutes while `requirements.txt` installs.
6. When it loads, check the sidebar footer: 🟢 means permanent PostgreSQL storage, 🟡 means temporary SQLite.

### Update the app later

Commit and push to `main`. Streamlit Cloud redeploys automatically:

```bash
git add .
git commit -m "Describe your change"
git push
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError` on Cloud | Make sure `requirements.txt` is in the repo root next to `app.py` |
| Data disappeared on Cloud | You're on SQLite (🟡). Restore your backup CSV, then set up Option A |
| `Could not open the database (postgresql)` | Check the `DATABASE_URL` secret, include `?sslmode=require`, and on Supabase use the pooler connection string |
| App is asleep | Free Cloud apps sleep after inactivity; click **Yes, get this app back up** |
| Theme looks light | Make sure `.streamlit/config.toml` was uploaded (folders starting with `.` are easy to miss) |

---

## A note on the challenge

Doubling every week is a mathematical exercise, not an investment plan. At 2× per week, $10 passes $1 million at week 17 and $1 billion at week 27. Real returns are nothing like this. Use the tracker to stay disciplined and measure progress, and treat the projection as a stretch goal, not a forecast.
