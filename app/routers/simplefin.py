"""SimpleFin connect + sync — the optional live-sync path.

Flow:
  1. User generates a setup token at their SimpleFin bridge provider
     (outside this app) and pastes it into POST /simplefin/connect.
  2. We exchange it for a permanent access URL (services.simplefin_client)
     and store it in a SimplefinConnection row — resolving the "Settings
     vs. a dedicated table" question CLAUDE.md flagged: a dedicated table,
     since one access URL can cover multiple bank accounts and a single
     global setting doesn't fit that.
  3. Connecting triggers an immediate first sync, so accounts/transactions
     show up right away rather than requiring a separate manual step.
  4. POST /simplefin/sync re-syncs later, on demand (no background
     scheduler — this is a "click to check for updates" app, not a
     always-on service).

The user's bank password is never seen by this app or by us — only by
their bank and SimpleFin's own auth flow. The access URL embeds a real
bearer credential (HTTP Basic Auth) and is never rendered into any
template once stored.
"""
from datetime import date, timedelta

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Account, SimplefinConnection
from app.services import simplefin_sync
from app.services.simplefin_client import SimpleFinClient
from app.templating import templates

router = APIRouter(prefix="/simplefin", tags=["simplefin"])


def _get_connection(db: Session) -> SimplefinConnection | None:
    # In practice there's ever only one row — see SimplefinConnection's
    # docstring for why it's still a table rather than a single setting.
    return db.query(SimplefinConnection).order_by(SimplefinConnection.id.desc()).first()


def _run_sync(db: Session, connection: SimplefinConnection) -> simplefin_sync.SyncResult:
    client = SimpleFinClient(access_url=connection.access_url)
    start_date = date.today() - timedelta(days=simplefin_sync.DEFAULT_SYNC_LOOKBACK_DAYS)
    response = client.get_accounts_and_transactions(start_date=start_date)
    return simplefin_sync.apply_sync_response(db, connection, response)


def _context(db: Session, connection: SimplefinConnection | None, sync_result=None, sync_error=None) -> dict:
    accounts = []
    if connection is not None:
        accounts = (
            db.query(Account)
            .filter(Account.simplefin_connection_id == connection.id)
            .order_by(Account.name)
            .all()
        )
    return {
        "connection": connection,
        "accounts": accounts,
        "sync_result": sync_result,
        "sync_error": sync_error,
        "active_nav": "simplefin",
    }


@router.get("/")
def index(request: Request, db: Session = Depends(get_db)):
    connection = _get_connection(db)
    return templates.TemplateResponse(request, "simplefin/index.html", _context(db, connection))


@router.post("/connect")
def connect(request: Request, setup_token: str = Form(...), db: Session = Depends(get_db)):
    try:
        access_url = SimpleFinClient().exchange_setup_token(setup_token.strip())
    except (ValueError, httpx.HTTPError) as exc:
        raise HTTPException(status_code=400, detail=f"couldn't connect: {exc}")

    connection = SimplefinConnection(access_url=access_url)
    db.add(connection)
    db.commit()

    sync_result, sync_error = None, None
    try:
        sync_result = _run_sync(db, connection)
    except (ValueError, httpx.HTTPError) as exc:
        # The connection itself is saved and good — only the immediate
        # first sync failed. Let the user retry via "Sync now" rather
        # than losing the connection over a transient sync error.
        sync_error = str(exc)

    return templates.TemplateResponse(request, "simplefin/index.html", _context(db, connection, sync_result, sync_error))


@router.post("/sync")
def sync(request: Request, db: Session = Depends(get_db)):
    connection = _get_connection(db)
    if connection is None:
        raise HTTPException(status_code=404, detail="no SimpleFin connection to sync — connect a bank first")

    sync_result, sync_error = None, None
    try:
        sync_result = _run_sync(db, connection)
    except (ValueError, httpx.HTTPError) as exc:
        sync_error = str(exc)

    return templates.TemplateResponse(request, "simplefin/index.html", _context(db, connection, sync_result, sync_error))
