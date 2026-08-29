"""Account CRUD endpoints.

Create/update use plain POST + a 303 redirect (not HTMX) — these are
infrequent, form-based actions, and progressive enhancement (works
without JS) matters more here than a snappier partial-page swap. Delete
isn't implemented yet: whether it should be a hard delete (only allowed
once an account has no transactions) or a soft-delete/archive flag is a
real design decision, not something to guess at — revisit when it's
actually needed.
"""
from decimal import Decimal

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Account, Transaction
from app.services.account_merge import execute_merge, find_duplicate_candidates
from app.services.balances import resolve_balance
from app.templating import templates

router = APIRouter(prefix="/accounts", tags=["accounts"])

# Presets for the account_type <select> in the create/edit forms. The model
# itself stores a free string (see models.py) — this list is a form-layer
# convenience, not a DB constraint, so an account with some other value
# (e.g. seeded directly, or from a future SimpleFin sync) still round-trips
# correctly; see _account_type_options.
ACCOUNT_TYPES = ["checking", "savings", "credit", "cash", "investment", "loan", "other"]


class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    institution: str | None = Field(default=None, max_length=120)
    account_type: str = Field(min_length=1, max_length=50)
    starting_balance: Decimal | None = None


class AccountUpdate(AccountCreate):
    pass


def _account_type_options(current: str) -> list[str]:
    if current in ACCOUNT_TYPES:
        return ACCOUNT_TYPES
    return [*ACCOUNT_TYPES, current]


def _account_summaries(db: Session) -> list[dict]:
    accounts = db.query(Account).order_by(Account.name).all()
    summaries = []
    for account in accounts:
        transaction_count = db.query(Transaction).filter(Transaction.account_id == account.id).count()
        summaries.append(
            {"account": account, "balance": resolve_balance(db, account), "transaction_count": transaction_count}
        )
    return summaries


@router.get("/")
def list_accounts(request: Request, db: Session = Depends(get_db)):
    context = {
        "accounts": _account_summaries(db),
        "account_types": ACCOUNT_TYPES,
        "active_nav": "accounts",
    }
    return templates.TemplateResponse(request, "accounts/index.html", context)


@router.post("/")
def create_account(
    name: str = Form(...),
    institution: str = Form(""),
    account_type: str = Form(...),
    starting_balance: str = Form(""),
    db: Session = Depends(get_db),
):
    try:
        payload = AccountCreate(
            name=name,
            institution=institution or None,
            account_type=account_type,
            starting_balance=starting_balance or None,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors())

    account = Account(
        name=payload.name,
        institution=payload.institution,
        account_type=payload.account_type,
        starting_balance=payload.starting_balance,
        source="manual",
    )
    db.add(account)
    db.commit()
    return RedirectResponse(url="/accounts/", status_code=303)


@router.get("/merge")
def merge_form(request: Request, db: Session = Depends(get_db)):
    # Declared before /{account_id} so "merge" is never treated as an
    # account id path param — route order matters here.
    accounts = db.query(Account).order_by(Account.name).all()
    context = {"accounts": accounts, "active_nav": "accounts"}
    return templates.TemplateResponse(request, "accounts/merge.html", context)


@router.post("/merge/preview")
def merge_preview(
    request: Request,
    source_account_id: int = Form(...),
    target_account_id: int = Form(...),
    db: Session = Depends(get_db),
):
    if source_account_id == target_account_id:
        raise HTTPException(status_code=400, detail="pick two different accounts to merge")

    source = db.get(Account, source_account_id)
    target = db.get(Account, target_account_id)
    if source is None or target is None:
        raise HTTPException(status_code=404, detail="account not found")

    pairs, unmatched = find_duplicate_candidates(db, source_account_id, target_account_id)
    context = {
        "source": source,
        "target": target,
        "pairs": pairs,
        "unmatched": unmatched,
        "active_nav": "accounts",
    }
    return templates.TemplateResponse(request, "accounts/merge_preview.html", context)


@router.post("/merge/confirm")
def merge_confirm(
    source_account_id: int = Form(...),
    target_account_id: int = Form(...),
    discard_transaction_ids: list[int] = Form([]),
    db: Session = Depends(get_db),
):
    if db.get(Account, source_account_id) is None or db.get(Account, target_account_id) is None:
        raise HTTPException(status_code=404, detail="account not found")

    execute_merge(
        db,
        source_account_id=source_account_id,
        target_account_id=target_account_id,
        discard_source_transaction_ids=set(discard_transaction_ids),
    )
    return RedirectResponse(url=f"/accounts/{target_account_id}", status_code=303)


@router.get("/{account_id}")
def get_account(request: Request, account_id: int, db: Session = Depends(get_db)):
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail=f"account {account_id} not found")

    transactions = (
        db.query(Transaction)
        .filter(Transaction.account_id == account_id)
        .order_by(Transaction.date.desc(), Transaction.id.desc())
        .all()
    )
    context = {
        "account": account,
        "transactions": transactions,
        "has_balance_data": any(t.balance is not None for t in transactions),
        "balance": resolve_balance(db, account),
        "account_types": _account_type_options(account.account_type),
        "active_nav": "accounts",
    }
    return templates.TemplateResponse(request, "accounts/detail.html", context)


@router.post("/{account_id}")
def update_account(
    account_id: int,
    name: str = Form(...),
    institution: str = Form(""),
    account_type: str = Form(...),
    starting_balance: str = Form(""),
    db: Session = Depends(get_db),
):
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail=f"account {account_id} not found")

    try:
        payload = AccountUpdate(
            name=name,
            institution=institution or None,
            account_type=account_type,
            starting_balance=starting_balance or None,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors())

    account.name = payload.name
    account.institution = payload.institution
    account.account_type = payload.account_type
    account.starting_balance = payload.starting_balance
    db.commit()
    return RedirectResponse(url=f"/accounts/{account_id}", status_code=303)
