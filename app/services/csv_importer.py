"""Parsing logic for imported bank statements.

TODO: support common CSV export formats (date/description/amount columns
vary by bank) and OFX. Likely approach: a small set of per-bank column
mapping presets, plus a manual column-mapping fallback in the UI for
banks we don't recognize.
"""
from pathlib import Path


def parse_csv(file_path: Path) -> list[dict]:
    """TODO: return a list of dicts like:
    {"date": ..., "amount": ..., "description": ..., "external_id": ...}
    """
    raise NotImplementedError("CSV parsing not yet implemented")


def parse_ofx(file_path: Path) -> list[dict]:
    """TODO: parse OFX/QFX format, same return shape as parse_csv."""
    raise NotImplementedError("OFX parsing not yet implemented")
