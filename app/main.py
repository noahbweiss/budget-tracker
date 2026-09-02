"""FastAPI app entrypoint.

Both run modes (venv's run.py and Docker's uvicorn CMD) point at
`app.main:app`, so there is exactly one app object regardless of how
it's launched.
"""
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from app.database import SessionLocal, run_migrations
from app.routers import accounts, dashboard, import_csv, plan, settings, simplefin, transactions
from app.services.categories import ensure_default_categories
from app.services.tags import ensure_system_tags
from app.templating import templates

# Creates tables (fresh install) or upgrades an existing database (stamping
# a pre-Alembic one at the baseline first) — see run_migrations's docstring
# in app/database.py.
run_migrations()

# Idempotent — only inserts if the categories table is empty. See
# app/services/categories.py for why this exists (no category-management
# UI yet, so the transaction categorization UI needs something to offer).
with SessionLocal() as _startup_db:
    ensure_default_categories(_startup_db)

# Also idempotent, but per-slug rather than empty-table-only — see
# app/services/tags.py's docstring for why.
with SessionLocal() as _startup_db:
    ensure_system_tags(_startup_db)

app = FastAPI(title="Finance Tracker")

# Anchored to this file's location (not cwd) so static resolution doesn't
# depend on where the process was launched from.
APP_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")

app.include_router(dashboard.router)
app.include_router(accounts.router)
app.include_router(plan.router)
app.include_router(transactions.router)
app.include_router(import_csv.router)
app.include_router(simplefin.router)
app.include_router(settings.router)


@app.get("/")
def root(request: Request):
    """Rendered home page. Currently a static empty-state shell — becomes
    a real dashboard/summary once accounts and transactions exist.
    """
    return templates.TemplateResponse(request, "index.html", {})


@app.get("/health")
def health():
    return {"status": "ok"}
