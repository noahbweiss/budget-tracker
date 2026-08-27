"""SimpleFin connect + sync — the optional live-sync path.

Flow (once implemented):
  1. User generates a setup token on simplefin.org (outside this app).
  2. User pastes that token into POST /simplefin/connect.
  3. We exchange it for a permanent access URL via services.simplefin_client
     and store it (in Settings or a dedicated table — TODO: decide which).
  4. POST /simplefin/sync pulls new transactions using the stored access URL.

The user's bank password is never seen by this app or by us — only by
their bank and SimpleFin's own auth flow.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db

router = APIRouter(prefix="/simplefin", tags=["simplefin"])


class ConnectRequest(BaseModel):
    setup_token: str


@router.post("/connect")
def connect(payload: ConnectRequest, db: Session = Depends(get_db)):
    """TODO: exchange setup_token for an access URL via services.simplefin_client."""
    return {"note": "stub — not yet implemented"}


@router.post("/sync")
def sync(db: Session = Depends(get_db)):
    """TODO: pull new transactions using the stored access URL."""
    return {"note": "stub — not yet implemented"}
