"""Account CRUD endpoints.

TODO: implement create/update/delete against app.models.Account. Kept
separate from transactions.py so account management and transaction
listing/import can evolve independently.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.get("/")
def list_accounts(db: Session = Depends(get_db)):
    """TODO: return all accounts. Stub returns empty list for now."""
    return []


@router.post("/")
def create_account(db: Session = Depends(get_db)):
    """TODO: accept an AccountCreate schema and persist it."""
    return {"note": "stub — not yet implemented"}
