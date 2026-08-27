"""CSV / OFX statement import — the zero-config default for getting bank
data into the app.

TODO: accept an uploaded file, hand it to services.csv_importer, and
insert resulting Transaction rows (with dedup via external_id where
possible, e.g. a hash of date+amount+description).
"""
from fastapi import APIRouter, Depends, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db

router = APIRouter(prefix="/import", tags=["import"])


@router.post("/csv")
async def import_csv(file: UploadFile, db: Session = Depends(get_db)):
    """TODO: parse the uploaded file via services.csv_importer and persist."""
    return {"filename": file.filename, "note": "stub — not yet implemented"}
