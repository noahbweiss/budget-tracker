# Finance Tracker

A local-first, open-source personal finance tracker. Track budget, spending,
and income across daily / weekly / monthly / quarterly / yearly views, with
support for connecting accounts across multiple banks.

**Status: skeleton stage.** Backend structure, models, and routes are stubbed
out. No frontend templates yet — this repo currently just gets you a running
FastAPI server with empty endpoints, so the project structure can be reviewed
before UI work starts.

## Design principles

- **Local-first.** Your data lives in a SQLite file on your own machine.
  Nothing is sent to a server we operate.
- **No baked-in paid API keys.** We never ship our own bank-API credentials,
  so forking this repo never makes anyone liable for someone else's usage.
- **Tiered bank connectivity.**
  - CSV / OFX import — zero-config default, works for anyone immediately.
  - Optional live sync via [SimpleFin](https://www.simplefin.org/) — you
    generate your own token and paste it in; no third party sees your bank
    password through this app.
- **One codebase, three ways to run it** — see below.

## Run it

### Option 1: Docker (recommended for non-developers)

```bash
cp .env.example .env
docker compose up
```

Then open http://localhost:8000

### Option 2: Python venv (recommended for developers / forking)

```bash
python -m venv venv
source venv/bin/activate      # venv\Scripts\activate on Windows
pip install -r requirements.txt
python run.py
```

Then open http://localhost:8000

### Option 3: Installed desktop app

Not built yet. Once the app is feature-complete, a Tauri shell (see
`src-tauri/`) will wrap this same backend into a native installer for
Mac / Windows / Linux, distributed via GitHub Releases. It will not
duplicate any app logic — it just spawns the same FastAPI backend.

## Project structure

```
app/
  main.py              FastAPI app entrypoint
  config.py            Settings (env vars, defaults)
  database.py           SQLAlchemy engine/session setup
  models.py             Account, Transaction, Category ORM models
  routers/               HTTP endpoints, grouped by feature
    dashboard.py         Time-range views (daily/weekly/monthly/quarterly/yearly)
    accounts.py          Account CRUD
    transactions.py       Transaction CRUD
    import_csv.py         CSV/OFX import
    simplefin.py           SimpleFin token connect + sync
  services/               Business logic, kept separate from routes
    aggregation.py         Time-bucketed spending/income calculations
    csv_importer.py         CSV/OFX parsing logic
    simplefin_client.py      SimpleFin API client
  templates/              Jinja2 templates (empty for now)
  static/                  CSS/JS/Chart.js assets (empty for now)
src-tauri/               Desktop app packaging (stub, filled in later)
tests/                   Test suite
data/                    SQLite database lives here (gitignored)
```

## Connecting a bank (once implemented)

1. Go to SimpleFin, generate a setup token tied to your bank login (this
   happens entirely outside this app).
2. In the app, paste that token into the "Connect a bank" screen.
3. The backend exchanges it for a permanent access URL and stores it in
   your local database. From then on, sync pulls new transactions.

Your bank password is never seen by this app.

## License

MIT — see `LICENSE`.
