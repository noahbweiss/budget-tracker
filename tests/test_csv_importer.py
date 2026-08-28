"""Tests for app.services.csv_importer.

Covers the real-world messiness of bank CSV exports: varying header
names, $/comma-formatted amounts, parenthesized negatives, and
debit/credit split columns instead of one signed amount column.
"""
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.services import csv_importer
from app.services.csv_importer import ColumnMapping


def write_csv(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content)
    return path


# ---- detect_mapping ----


def test_detects_single_amount_column():
    mapping = csv_importer.detect_mapping(["Date", "Description", "Amount"])
    assert mapping == ColumnMapping(date="Date", description="Description", amount="Amount")


def test_detects_common_header_variants():
    mapping = csv_importer.detect_mapping(["Transaction Date", "Memo", "Amount"])
    assert mapping == ColumnMapping(date="Transaction Date", description="Memo", amount="Amount")


def test_detects_debit_credit_split_columns():
    mapping = csv_importer.detect_mapping(["Posted Date", "Description", "Debit", "Credit"])
    assert mapping == ColumnMapping(date="Posted Date", description="Description", debit="Debit", credit="Credit")


def test_returns_none_for_unrecognized_headers():
    assert csv_importer.detect_mapping(["Col A", "Col B", "Col C"]) is None


def test_returns_none_when_amount_columns_missing():
    assert csv_importer.detect_mapping(["Date", "Description"]) is None


# ---- parse_csv: single amount column ----


def test_parse_csv_single_amount_column(tmp_path):
    path = write_csv(
        tmp_path,
        "statement.csv",
        "Date,Description,Amount\n"
        "2026-07-01,Paycheck,3200.00\n"
        "2026-07-02,Rent,-1450.00\n",
    )
    rows = csv_importer.parse_csv(path)
    assert len(rows) == 2
    assert rows[0]["date"] == date(2026, 7, 1)
    assert rows[0]["description"] == "Paycheck"
    assert rows[0]["amount"] == Decimal("3200.00")
    assert rows[1]["amount"] == Decimal("-1450.00")


def test_parse_csv_handles_dollar_signs_and_commas(tmp_path):
    path = write_csv(
        tmp_path,
        "statement.csv",
        "Date,Description,Amount\n2026-07-01,Big Purchase,\"-$1,234.56\"\n",
    )
    rows = csv_importer.parse_csv(path)
    assert rows[0]["amount"] == Decimal("-1234.56")


def test_parse_csv_handles_parenthesized_negatives(tmp_path):
    path = write_csv(
        tmp_path,
        "statement.csv",
        "Date,Description,Amount\n2026-07-01,Fee,($12.00)\n",
    )
    rows = csv_importer.parse_csv(path)
    assert rows[0]["amount"] == Decimal("-12.00")


def test_parse_csv_handles_mmddyyyy_dates(tmp_path):
    path = write_csv(tmp_path, "statement.csv", "Date,Description,Amount\n07/04/2026,Cookout,-40.00\n")
    rows = csv_importer.parse_csv(path)
    assert rows[0]["date"] == date(2026, 7, 4)


# ---- parse_csv: debit/credit split columns ----


def test_parse_csv_debit_credit_columns(tmp_path):
    path = write_csv(
        tmp_path,
        "statement.csv",
        "Date,Description,Debit,Credit\n"
        "2026-07-01,Paycheck,,3200.00\n"
        "2026-07-02,Rent,1450.00,\n",
    )
    rows = csv_importer.parse_csv(path)
    assert rows[0]["amount"] == Decimal("3200.00")
    assert rows[1]["amount"] == Decimal("-1450.00")


# ---- parse_csv: explicit mapping override ----


def test_parse_csv_with_explicit_mapping(tmp_path):
    path = write_csv(tmp_path, "statement.csv", "d,desc,amt\n2026-07-01,Thing,-5.00\n")
    mapping = ColumnMapping(date="d", description="desc", amount="amt")
    rows = csv_importer.parse_csv(path, mapping=mapping)
    assert rows[0]["description"] == "Thing"


def test_parse_csv_raises_when_no_mapping_detected_or_given(tmp_path):
    path = write_csv(tmp_path, "statement.csv", "Col A,Col B\nx,y\n")
    with pytest.raises(ValueError):
        csv_importer.parse_csv(path)


# ---- external_id: stable + disambiguated within a file ----


def test_external_id_is_stable_across_reparse(tmp_path):
    path = write_csv(tmp_path, "statement.csv", "Date,Description,Amount\n2026-07-01,Coffee,-5.00\n")
    first = csv_importer.parse_csv(path)
    second = csv_importer.parse_csv(path)
    assert first[0]["external_id"] == second[0]["external_id"]


def test_external_id_disambiguates_identical_rows_in_one_file(tmp_path):
    path = write_csv(
        tmp_path,
        "statement.csv",
        "Date,Description,Amount\n2026-07-01,Coffee,-5.00\n2026-07-01,Coffee,-5.00\n",
    )
    rows = csv_importer.parse_csv(path)
    assert rows[0]["external_id"] != rows[1]["external_id"]


# ---- sniff_headers ----


def test_sniff_headers_returns_raw_header_row(tmp_path):
    path = write_csv(tmp_path, "statement.csv", "Foo,Bar,Baz\n1,2,3\n")
    assert csv_importer.sniff_headers(path) == ["Foo", "Bar", "Baz"]


# ---- parse_ofx ----

SAMPLE_OFX = """OFXHEADER:100
DATA:OFXSGML
VERSION:102

<OFX>
<BANKMSGSRSV1>
<STMTTRNRS>
<STMTRS>
<BANKTRANLIST>
<STMTTRN>
<TRNTYPE>DEBIT
<DTPOSTED>20260701
<TRNAMT>-42.50
<FITID>2026070100001
<NAME>Grocery Store
</STMTTRN>
<STMTTRN>
<TRNTYPE>CREDIT
<DTPOSTED>20260702
<TRNAMT>1500.00
<FITID>2026070200002
<NAME>Paycheck
<MEMO>Direct deposit
</STMTTRN>
</BANKTRANLIST>
</STMTRS>
</STMTRNRS>
</BANKMSGSRSV1>
</OFX>
"""


def test_parse_ofx_extracts_transactions(tmp_path):
    path = tmp_path / "statement.ofx"
    path.write_text(SAMPLE_OFX)
    rows = csv_importer.parse_ofx(path)

    assert len(rows) == 2
    assert rows[0]["date"] == date(2026, 7, 1)
    assert rows[0]["amount"] == Decimal("-42.50")
    assert rows[0]["description"] == "Grocery Store"
    assert rows[0]["external_id"] == "2026070100001"

    assert rows[1]["description"] == "Paycheck — Direct deposit"
    assert rows[1]["external_id"] == "2026070200002"


def test_parse_ofx_empty_file_returns_empty_list(tmp_path):
    path = tmp_path / "empty.ofx"
    path.write_text("OFXHEADER:100\n<OFX></OFX>\n")
    assert csv_importer.parse_ofx(path) == []
