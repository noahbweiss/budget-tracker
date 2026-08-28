"""CSV / OFX statement import — the zero-config default for getting bank
data into the app.

Flow: GET / (upload form) -> POST /upload (save to a temp file, parse a
preview) -> [optional POST /preview to adjust CSV column mapping, HTMX] ->
POST /confirm (re-parse the same temp file, insert Transaction rows,
dedup via external_id) or POST /cancel (discard).

The temp file is the only state carried between steps — everything else
(account_id, file_kind, and the confirmed column mapping) round-trips
through hidden form fields, so there's no server-side session and no new
DB table for "pending imports".
"""
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Account, Transaction
from app.services import csv_importer
from app.services.csv_importer import ColumnMapping
from app.templating import templates

router = APIRouter(prefix="/import", tags=["import"])

PREVIEW_ROW_LIMIT = 50

# Temp uploads live outside the project/data dir entirely (the OS temp
# dir) — they're transient staging, not app data, and this keeps tests
# from ever writing into the working tree.
IMPORT_TMP_DIR = Path(tempfile.gettempdir()) / "finance-tracker-imports"

SUPPORTED_EXTENSIONS = {".csv": "csv", ".ofx": "ofx", ".qfx": "ofx"}


def _temp_path(token: str, file_kind: str) -> Path:
    IMPORT_TMP_DIR.mkdir(parents=True, exist_ok=True)
    suffix = "csv" if file_kind == "csv" else "ofx"
    return IMPORT_TMP_DIR / f"{token}.{suffix}"


def _mapping_from_form(date_column: str, description_column: str, amount_column: str, debit_column: str, credit_column: str) -> ColumnMapping | None:
    if not date_column or not description_column:
        return None
    if amount_column:
        return ColumnMapping(date=date_column, description=description_column, amount=amount_column)
    if debit_column and credit_column:
        return ColumnMapping(date=date_column, description=description_column, debit=debit_column, credit=credit_column)
    return None


def _parse_rows(path: Path, file_kind: str, mapping: ColumnMapping | None) -> list[dict]:
    if file_kind == "ofx":
        return csv_importer.parse_ofx(path)
    return csv_importer.parse_csv(path, mapping=mapping)


@router.get("/")
def import_form(request: Request, db: Session = Depends(get_db)):
    accounts = db.query(Account).order_by(Account.name).all()
    context = {"accounts": accounts, "active_nav": "import"}
    return templates.TemplateResponse(request, "import/index.html", context)


@router.post("/upload")
async def upload(
    request: Request,
    account_id: int = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail=f"account {account_id} not found")

    extension = Path(file.filename or "").suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"unsupported file type {extension!r} — use .csv, .ofx, or .qfx")
    file_kind = SUPPORTED_EXTENSIONS[extension]

    token = uuid.uuid4().hex
    path = _temp_path(token, file_kind)
    path.write_bytes(await file.read())

    headers = csv_importer.sniff_headers(path) if file_kind == "csv" else []
    mapping = csv_importer.detect_mapping(headers) if file_kind == "csv" else None

    context = _preview_context(path, file_kind, mapping, headers, account, token)
    return templates.TemplateResponse(request, "import/preview.html", context)


@router.post("/preview")
def preview(
    request: Request,
    token: str = Form(...),
    account_id: int = Form(...),
    file_kind: str = Form(...),
    date_column: str = Form(""),
    description_column: str = Form(""),
    amount_column: str = Form(""),
    debit_column: str = Form(""),
    credit_column: str = Form(""),
    db: Session = Depends(get_db),
):
    account = db.get(Account, account_id)
    path = _temp_path(token, file_kind)
    if account is None or not path.exists():
        raise HTTPException(status_code=404, detail="import session not found or expired")

    mapping = _mapping_from_form(date_column, description_column, amount_column, debit_column, credit_column)
    headers = csv_importer.sniff_headers(path) if file_kind == "csv" else []

    context = _preview_context(path, file_kind, mapping, headers, account, token)
    template_name = "import/_preview_body.html" if request.headers.get("hx-request") == "true" else "import/preview.html"
    return templates.TemplateResponse(request, template_name, context)


def _preview_context(path: Path, file_kind: str, mapping: ColumnMapping | None, headers: list[str], account: Account, token: str) -> dict:
    error = None
    rows: list[dict] = []
    try:
        rows = _parse_rows(path, file_kind, mapping)
    except ValueError as exc:
        error = str(exc)

    return {
        "account": account,
        "token": token,
        "file_kind": file_kind,
        "headers": headers,
        "mapping": mapping,
        "error": error,
        "row_count": len(rows),
        "preview_rows": rows[:PREVIEW_ROW_LIMIT],
        "more_rows": max(0, len(rows) - PREVIEW_ROW_LIMIT),
        "active_nav": "import",
    }


@router.post("/confirm")
def confirm(
    request: Request,
    token: str = Form(...),
    account_id: int = Form(...),
    file_kind: str = Form(...),
    date_column: str = Form(""),
    description_column: str = Form(""),
    amount_column: str = Form(""),
    debit_column: str = Form(""),
    credit_column: str = Form(""),
    db: Session = Depends(get_db),
):
    account = db.get(Account, account_id)
    path = _temp_path(token, file_kind)
    if account is None or not path.exists():
        raise HTTPException(status_code=404, detail="import session not found or expired")

    mapping = _mapping_from_form(date_column, description_column, amount_column, debit_column, credit_column)
    rows = _parse_rows(path, file_kind, mapping)

    existing_ids = {
        t.external_id
        for t in db.query(Transaction.external_id).filter(Transaction.account_id == account.id).all()
        if t.external_id
    }

    imported = 0
    skipped = 0
    for row in rows:
        if row["external_id"] in existing_ids:
            skipped += 1
            continue
        db.add(
            Transaction(
                account_id=account.id,
                date=row["date"],
                amount=row["amount"],
                description=row["description"],
                external_id=row["external_id"],
            )
        )
        existing_ids.add(row["external_id"])
        imported += 1
    db.commit()

    path.unlink(missing_ok=True)

    context = {
        "account": account,
        "imported": imported,
        "skipped": skipped,
        "active_nav": "import",
    }
    return templates.TemplateResponse(request, "import/result.html", context)


@router.post("/cancel")
def cancel(token: str = Form(...), file_kind: str = Form("csv")):
    _temp_path(token, file_kind).unlink(missing_ok=True)
    return RedirectResponse(url="/import/", status_code=303)
