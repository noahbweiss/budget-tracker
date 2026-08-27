"""Transaction listing/editing endpoints.

TODO: support filtering by account, category, and date range once the
frontend needs it. Categorization (assigning/editing a transaction's
category) will likely live here too.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.get("/")
def list_transactions(db: Session = Depends(get_db)):
    """TODO: return transactions, with optional filters. Stub returns []."""
    return []
