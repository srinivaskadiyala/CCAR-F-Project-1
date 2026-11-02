"""Deterministic checks run on Agent 3's merged output before the final write."""
from __future__ import annotations

import csv
import re
from pathlib import Path

from schemas import MergeReport, Patch
from tools import calc_stats

DATE_RE = re.compile(r"^\d{2}-[A-Z]{3}-\d{4}$")
CALC_HEADERS = {"Total", "Avg"}
TOLERANCE = 0.005


def read_csv(path: Path) -> list[list[str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return [row for row in csv.reader(f)]


def write_csv(path: Path, rows: list[list[str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)


def check_shape(original: list[list[str]], merged: list[list[str]]) -> list[str]:
    errs: list[str] = []
    if len(original) != len(merged):
        errs.append(f"row count {len(merged)} != original {len(original)}")
    elif original[0] != merged[0]:
        errs.append("header row changed")
    elif any(len(a) != len(b) for a, b in zip(original, merged)):
        errs.append("column count changed in at least one row")
    return errs


def check_dates(merged: list[list[str]], skip: set[tuple[int, str]] = frozenset()) -> list[str]:
    """Every cell in a 'Date' column (not the TOTAL row) must be DD-MON-YYYY.

    `skip` holds (row, column) cells that were reported as unverifiable.
    """
    header = merged[0]
    errs: list[str] = []
    for ci, name in enumerate(header):
        if name != "Date":
            continue
        for ri, row in enumerate(merged[1:], start=1):
            v = _cell(row, ci).strip()
            if not v or v == "TOTAL" or (ri, name) in skip:
                continue
            if not DATE_RE.match(v):
                errs.append(f"row {ri} Date {v!r} is not DD-MON-YYYY")
    return errs


def _cell(row: list[str], i: int) -> str:
    """Cell text, treating cells missing from a short or blank row as empty."""
    return row[i] if i < len(row) else ""


def check_totals(merged: list[list[str]]) -> list[str]:
    """Verify Total/Avg columns per row and the TOTAL row per column."""
    header = merged[0]
    calc_cols = {i for i, h in enumerate(header) if h in CALC_HEADERS}
    label_cols = {i for i, h in enumerate(header) if h in ("Date", "Item")}
    raw_cols = [i for i in range(len(header)) if i not in calc_cols | label_cols]
    errs: list[str] = []

    numbered = [(ri, r) for ri, r in enumerate(merged[1:], start=1) if r]   # skip blank lines
    data = [(ri, r) for ri, r in numbered if _cell(r, 0).strip() != "TOTAL"]
    total_rows = [(ri, r) for ri, r in numbered if _cell(r, 0).strip() == "TOTAL"]

    def compare(ri: int, col: int, expected: float | None) -> None:
        cell = _cell(merged[ri], col).strip()
        if not cell or expected is None:
            return
        try:
            if abs(float(cell) - expected) > TOLERANCE:
                errs.append(f"row {ri} {header[col]}: {cell} should be {expected:g}")
        except ValueError:
            errs.append(f"row {ri} {header[col]}: {cell!r} is not numeric")

    for ri, row in data:
        stats = calc_stats([_cell(row, i) for i in raw_cols])
        if stats.get("isError"):
            errs.append(f"row {ri}: {stats['message']}")
            continue
        for ci in calc_cols:
            compare(ri, ci, stats["sum"] if header[ci] == "Total" else stats["average"])

    for ri, row in total_rows:
        # Total and raw columns sum the data rows; a filled Avg is the mean of the data rows' Avgs.
        for ci in raw_cols + sorted(calc_cols):
            stats = calc_stats([_cell(r, ci) for _, r in data])
            if not stats.get("isError"):
                compare(ri, ci, stats["average"] if header[ci] == "Avg" else stats["sum"])
    return errs


def check_patches_accounted(
    original: list[list[str]], merged: list[list[str]],
    patches: list[Patch], report: MergeReport,
) -> list[str]:
    """Each patch must be in the merged file or listed as a conflict."""
    header = original[0]
    conflicted = {(c.get("row"), c.get("column")) for c in report.conflicts}
    errs: list[str] = []
    for p in patches:
        if (p.row, p.column) in conflicted:
            continue
        if p.column not in header:
            errs.append(f"patch column {p.column!r} not in header")
            continue
        if not 1 <= p.row < len(merged):
            errs.append(f"patch row {p.row} {p.column}: row out of range (1-{len(merged) - 1})")
            continue
        got = _cell(merged[p.row], header.index(p.column)).strip()
        if got != p.new.strip():
            errs.append(f"patch row {p.row} {p.column}: expected {p.new!r}, merged has {got!r}")
    return errs


def check_untouched(
    original: list[list[str]], merged: list[list[str]],
    patches: list[Patch], report: MergeReport,
) -> list[str]:
    """Every cell that differs from the original must be covered by a patch.

    Enforces 'raw data cells are never changed' independently of the totals check.
    A cell reported as a conflict must keep its original value (neither patch applied).
    """
    header = original[0]
    patched = {(p.row, p.column): p.new.strip() for p in patches}
    conflicted = {(c.get("row"), c.get("column")) for c in report.conflicts}
    errs: list[str] = []
    for ri, (orig_row, new_row) in enumerate(zip(original, merged)):
        if ri == 0:
            continue
        for ci in range(max(len(orig_row), len(new_row))):
            old, new = _cell(orig_row, ci), _cell(new_row, ci)
            if old == new:
                continue
            key = (ri, header[ci] if ci < len(header) else f"col{ci}")
            if key in conflicted:
                errs.append(f"row {ri} {key[1]}: reported as a conflict but was changed to {new!r}")
            elif patched.get(key) != new.strip():
                errs.append(f"row {ri} {key[1]}: changed from {old!r} to {new!r} without a matching patch")
    return errs


def find_conflicts(patch_sets: list[list[Patch]]) -> set[tuple[int, str]]:
    seen: dict[tuple[int, str], str] = {}
    out: set[tuple[int, str]] = set()
    for patches in patch_sets:
        for p in patches:
            key = (p.row, p.column)
            if key in seen and seen[key] != p.new:
                out.add(key)
            seen.setdefault(key, p.new)
    return out


def validate_merge(
    original: list[list[str]], merged: list[list[str]],
    patches: list[Patch], report: MergeReport,
) -> list[str]:
    skip = {(u.get("row"), u.get("column")) for u in report.unverifiable}
    errs = check_shape(original, merged)
    if errs:
        return errs
    return (check_dates(merged, skip) + check_totals(merged)
            + check_patches_accounted(original, merged, patches, report)
            + check_untouched(original, merged, patches, report))

