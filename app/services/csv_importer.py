"""Parsing logic for imported bank statements.

Two formats, two very different problems:

- **CSV** has no fixed schema — every bank's export has different column
  names, and some split a single signed amount into separate Debit/Credit
  columns. `detect_mapping()` recognizes common header-name variants (not
  a hardcoded per-bank list — this project has no real sample exports
  from specific banks to build/verify presets against, so a flexible
  auto-detector plus a manual override in the UI is the honest approach,
  not fabricated "Chase preset"/"Amex preset" support). When detection
  fails, the router falls back to a manual column-mapping UI built from
  `sniff_headers()`.
- **OFX/QFX** is self-describing (it names its own fields) and, unlike
  CSV, gives each transaction a real stable id (`FITID`) — no mapping or
  synthetic id needed.

Both return the same row shape: {"date": date, "amount": Decimal,
"description": str, "external_id": str, "balance": Decimal | None}.
external_id is the dedup key routers/import_csv.py checks against
existing Transaction.external_id for a given account before inserting.
`balance` — the account's running balance as of that row, when the CSV
happens to report one — is optional and CSV-only; OFX has no standard
per-transaction balance field (LEDGERBAL/AVAILBAL are statement-level,
not per-row), so parse_ofx() always returns None for it.
"""
import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import csv as csv_module

# Header names (lowercased, matched by substring) recognized for each
# logical column. Order matters within a list only in that the first
# substring match wins, but there's no meaningful overlap between these.
_DATE_HEADERS = ["transaction date", "posted date", "post date", "date"]
_DESCRIPTION_HEADERS = ["description", "memo", "payee", "name"]
_AMOUNT_HEADERS = ["transaction amount", "amount"]
_DEBIT_HEADERS = ["debit", "withdrawal"]
_CREDIT_HEADERS = ["credit", "deposit"]
_BALANCE_HEADERS = ["running balance", "posted balance", "account balance", "balance"]

# Tried in order; the first that parses the value is used. ISO first
# (unambiguous), then US-style (this app makes no locale assumption
# beyond that — DD/MM-first banks aren't handled, a known limitation of
# guessing from format alone; manual mapping doesn't help with this
# specific ambiguity either, since it's a value format, not a column
# choice, but it's honest to note rather than silently mis-parse).
_DATE_FORMATS = ["%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d-%b-%Y", "%b %d, %Y"]


@dataclass(frozen=True)
class ColumnMapping:
    date: str
    description: str
    amount: str | None = None
    debit: str | None = None
    credit: str | None = None
    balance: str | None = None


def sniff_headers(file_path: Path) -> list[str]:
    """Return the CSV's header row as-is — used to build the manual
    column-mapping UI when detect_mapping() can't confidently guess.
    """
    with file_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv_module.reader(f)
        return next(reader, [])


def detect_mapping(headers: list[str]) -> ColumnMapping | None:
    """Guess a ColumnMapping from header names. Returns None if a date
    column or a usable amount column (single amount, or both debit and
    credit) can't be confidently found.
    """
    by_lower = {h.strip().lower(): h for h in headers}

    date_col = _find_header(by_lower, _DATE_HEADERS)
    description_col = _find_header(by_lower, _DESCRIPTION_HEADERS)
    amount_col = _find_header(by_lower, _AMOUNT_HEADERS)
    debit_col = _find_header(by_lower, _DEBIT_HEADERS)
    credit_col = _find_header(by_lower, _CREDIT_HEADERS)
    balance_col = _find_header(by_lower, _BALANCE_HEADERS)

    if date_col is None or description_col is None:
        return None
    if amount_col is not None:
        return ColumnMapping(date=date_col, description=description_col, amount=amount_col, balance=balance_col)
    if debit_col is not None and credit_col is not None:
        return ColumnMapping(
            date=date_col, description=description_col, debit=debit_col, credit=credit_col, balance=balance_col
        )
    return None


def _find_header(by_lower: dict[str, str], candidates: list[str]) -> str | None:
    for candidate in candidates:
        for lower_name, original_name in by_lower.items():
            if candidate in lower_name:
                return original_name
    return None


def parse_csv(file_path: Path, mapping: ColumnMapping | None = None) -> list[dict]:
    """Parse a CSV file into transaction dicts. Uses `mapping` if given,
    otherwise tries to auto-detect one via detect_mapping().

    Raises:
        ValueError: no mapping was given and none could be auto-detected.
    """
    with file_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv_module.DictReader(f)
        headers = reader.fieldnames or []
        if mapping is None:
            mapping = detect_mapping(headers)
        if mapping is None:
            raise ValueError(
                "couldn't detect date/amount columns from the CSV header — "
                "pass an explicit ColumnMapping"
            )

        rows = []
        seen_ids: dict[str, int] = {}
        for raw_row in reader:
            parsed_date = _parse_date(raw_row[mapping.date])
            description = (raw_row.get(mapping.description) or "").strip()
            amount = _resolve_amount(raw_row, mapping)
            external_id = _dedupe_id(_row_hash(parsed_date, amount, description), seen_ids)
            balance_raw = raw_row.get(mapping.balance) if mapping.balance else None
            balance = _parse_amount(balance_raw) if balance_raw and balance_raw.strip() else None
            rows.append(
                {
                    "date": parsed_date,
                    "description": description,
                    "amount": amount,
                    "external_id": external_id,
                    "balance": balance,
                }
            )
        return rows


def _resolve_amount(raw_row: dict, mapping: ColumnMapping) -> Decimal:
    if mapping.amount is not None:
        return _parse_amount(raw_row[mapping.amount])
    debit = _parse_amount(raw_row.get(mapping.debit) or "0") if mapping.debit else Decimal("0")
    credit = _parse_amount(raw_row.get(mapping.credit) or "0") if mapping.credit else Decimal("0")
    # Debit/credit columns hold unsigned magnitudes by convention — a
    # value in the debit column is money out regardless of its own sign.
    return abs(credit) - abs(debit)


_AMOUNT_CLEANUP_RE = re.compile(r"[^0-9.\-]")


def _parse_amount(raw: str) -> Decimal:
    raw = raw.strip()
    if not raw:
        raise ValueError("empty amount value")
    negative = raw.startswith("(") and raw.endswith(")")
    if negative:
        raw = raw[1:-1]
    cleaned = _AMOUNT_CLEANUP_RE.sub("", raw)
    try:
        value = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"unparseable amount: {raw!r}") from exc
    return -abs(value) if negative else value


def _parse_date(raw: str) -> date:
    raw = raw.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognized date format: {raw!r}")


def _row_hash(parsed_date: date, amount: Decimal, description: str) -> str:
    key = f"{parsed_date.isoformat()}|{amount}|{description}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _dedupe_id(base_id: str, seen_ids: dict[str, int]) -> str:
    """Disambiguate genuinely identical rows within one file (e.g. two
    $5 coffees on the same day) so they don't collapse into a single
    external_id — that would make the second one look like a duplicate
    of the first on import and get silently dropped.
    """
    count = seen_ids.get(base_id, 0)
    seen_ids[base_id] = count + 1
    return base_id if count == 0 else f"{base_id}-{count + 1}"


# ---- OFX ----

_OFX_TRANSACTION_RE = re.compile(r"<STMTTRN>(.*?)</STMTTRN>", re.DOTALL)
_OFX_FIELD_RE = re.compile(r"<(\w+)>([^<\r\n]*)")


def parse_ofx(file_path: Path) -> list[dict]:
    """Parse OFX/QFX. OFX 1.x is SGML — tags often aren't closed — so
    this deliberately doesn't use an XML parser; it extracts each
    <STMTTRN>...</STMTTRN> block and pulls out the handful of fields
    this app needs (DTPOSTED, TRNAMT, NAME, MEMO, FITID) with a regex.
    This covers the common case; a malformed or unusually-structured OFX
    file (multiple accounts in one file, non-standard field ordering
    inside a transaction block) may need real ofxparse-style handling —
    not built here to avoid a new dependency for a format most banks
    only offer as a secondary option to CSV.
    """
    text = file_path.read_text(encoding="utf-8-sig", errors="replace")
    rows = []
    for block in _OFX_TRANSACTION_RE.findall(text):
        fields = {m.group(1): m.group(2).strip() for m in _OFX_FIELD_RE.finditer(block)}

        name = fields.get("NAME", "").strip()
        memo = fields.get("MEMO", "").strip()
        description = f"{name} — {memo}" if name and memo else (name or memo)

        rows.append(
            {
                "date": _parse_ofx_date(fields["DTPOSTED"]),
                "amount": Decimal(fields["TRNAMT"]),
                "description": description,
                "external_id": fields.get("FITID") or _row_hash(
                    _parse_ofx_date(fields["DTPOSTED"]), Decimal(fields["TRNAMT"]), description
                ),
                # OFX has no standard per-transaction balance field.
                "balance": None,
            }
        )
    return rows


def _parse_ofx_date(raw: str) -> date:
    # DTPOSTED is "YYYYMMDD" optionally followed by "HHMMSS[.xxx][tz]" —
    # only the first 8 characters matter here.
    return datetime.strptime(raw[:8], "%Y%m%d").date()
