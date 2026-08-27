"""FastAPI app entrypoint.

Both run modes (venv's run.py and Docker's uvicorn CMD) point at
`app.main:app`, so there is exactly one app object regardless of how
it's launched.
"""
from fastapi import FastAPI

from app.database import Base, engine
from app.routers import accounts, dashboard, import_csv, simplefin, transactions

# TODO: replace with Alembic migrations once the schema stabilizes.
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Finance Tracker")

app.include_router(dashboard.router)
app.include_router(accounts.router)
app.include_router(transactions.router)
app.include_router(import_csv.router)
app.include_router(simplefin.router)


@app.get("/")
def root():
    """Placeholder root route. TODO: replace with the rendered dashboard
    template once frontend work starts.
    """
    return {"status": "ok", "app": "finance-tracker", "note": "skeleton stage — no UI yet"}


@app.get("/health")
def health():
    return {"status": "ok"}
