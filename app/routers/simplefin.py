"""SimpleFin connect + sync — the optional live-sync path.

Flow:
  1. User generates a setup token at their SimpleFin bridge provider
     (outside this app) and pastes it into POST /simplefin/connect.
  2. We exchange it for a permanent access URL (services.simplefin_client)
     and store it in a SimplefinConnection row — resolving the "Settings
     vs. a dedicated table" question CLAUDE.md flagged: a dedicated table,
     since one access URL can cover multiple bank accounts.
  3. Every sync (the immediate first one, and every "Sync now" after)
     partitions the remote accounts into ones already linked locally
     (synced immediately, no interruption) and ones with no local match
     yet. The unmatched ones stop at a review step — "create new" or
     "link to an existing account" — before anything is created. This
     is deliberate, not extra friction for its own sake: silently
     auto-creating a new local Account for every unmatched remote one is
     exactly what caused a real duplicate (a CSV-imported credit card
     and its SimpleFin connection ending up as two separate accounts
     with no link between them — see app/services/account_merge.py,
     built to clean up after that happened). Asking once per newly
     discovered account is cheap; a silent duplicate is not.

The user's bank password is never seen by this app or by us — only by
their bank and SimpleFin's own auth flow. The access URL embeds a real
bearer credential (HTTP Basic Auth) and is never rendered into any
template once stored.
"""
import json
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


def _fetch_and_partition(connection: SimplefinConnection, db: Session) -> tuple[list[dict], list[dict], list[str]]:
    client = SimpleFinClient(access_url=connection.access_url)
    start_date = date.today() - timedelta(days=simplefin_sync.DEFAULT_SYNC_LOOKBACK_DAYS)
    response = client.get_accounts_and_transactions(start_date=start_date)
    matched, new = simplefin_sync.partition_response(db, connection, response)
    return matched, new, list(response.get("errors") or [])


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


def _run_sync_or_review(request: Request, db: Session, connection: SimplefinConnection):
    """Shared by /connect and /sync: fetch + sync already-matched accounts
    immediately, and if anything unmatched turns up, render the review
    step instead of the normal connected-status page.
    """
    try:
        matched, new, api_errors = _fetch_and_partition(connection, db)
    except (ValueError, httpx.HTTPError) as exc:
        return templates.TemplateResponse(request, "simplefin/index.html", _context(db, connection, sync_error=str(exc)))

    sync_result = simplefin_sync.sync_matched_accounts(db, connection, matched)
    sync_result.errors = api_errors

    if new:
        existing_accounts = db.query(Account).filter(Account.simplefin_account_id.is_(None)).order_by(Account.name).all()
        context = {
            "connection": connection,
            "new_accounts": new,
            "existing_accounts": existing_accounts,
            "sync_result": sync_result,
            "lookback_days": simplefin_sync.DEFAULT_SYNC_LOOKBACK_DAYS,
            "active_nav": "simplefin",
        }
        return templates.TemplateResponse(request, "simplefin/new_accounts.html", context)

    return templates.TemplateResponse(request, "simplefin/index.html", _context(db, connection, sync_result))


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

    # The connection itself is saved and good even if this first sync
    # attempt fails — _run_sync_or_review handles that by showing the
    # error rather than raising, so "Sync now" can retry later.
    return _run_sync_or_review(request, db, connection)


@router.post("/sync")
def sync(request: Request, db: Session = Depends(get_db)):
    connection = _get_connection(db)
    if connection is None:
        raise HTTPException(status_code=404, detail="no SimpleFin connection to sync — connect a bank first")

    return _run_sync_or_review(request, db, connection)


@router.post("/resolve-new-accounts")
def resolve_new_accounts(
    request: Request,
    remote_account_json: list[str] = Form(...),
    choice: list[str] = Form(...),
    db: Session = Depends(get_db),
):
    connection = _get_connection(db)
    if connection is None:
        raise HTTPException(status_code=404, detail="no SimpleFin connection")

    created = 0
    linked = 0
    for raw, chosen in zip(remote_account_json, choice):
        remote_account = json.loads(raw)
        if chosen == "new":
            simplefin_sync.create_new_account(db, connection, remote_account)
            created += 1
        else:
            simplefin_sync.link_to_existing_account(db, connection, remote_account, int(chosen))
            linked += 1

    sync_result = simplefin_sync.SyncResult(accounts_updated=created + linked)
    return templates.TemplateResponse(request, "simplefin/index.html", _context(db, connection, sync_result))
