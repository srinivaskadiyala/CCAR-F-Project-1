import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from schemas import MergeReport, Patch  # noqa: E402
from validate import (check_dates, check_shape, check_totals, find_conflicts,  # noqa: E402
                      read_csv, validate_merge)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
APP1 = FIXTURES / "sample6.csv"       # original 6-row sample
REAL = Path(__file__).resolve().parents[1] / "app1.csv"

FIXED = [
    ["Date", "Item", "Jan", "Feb", "Mar", "Total", "Avg"],
    ["04-MAR-2026", "Widgets", "10", "20", "30", "60", "20"],
    ["05-MAR-2026", "Gadgets", "15", "25", "35", "75", "25"],
    ["06-MAR-2026", "Gizmos", "8", "12", "", "20", "10"],
    ["07-MAR-2026", "Doohickeys", "40", "50", "60", "150", "50"],
    ["13-MAR-2026", "Thingamajigs", "5", "5", "5", "15", "5"],
    ["TOTAL", "", "78", "112", "130", "320", ""],
]


def test_read_csv_handles_bom() -> None:
    rows = read_csv(APP1)
    assert rows[0][0] == "Date"


def test_original_sample_has_known_errors() -> None:
    errs = check_totals(read_csv(APP1))
    joined = " ".join(errs)
    assert "Gadgets" not in joined  # row-based messages use row numbers
    assert "row 2 Total: 80 should be 75" in errs
    assert "row 4 Avg: 55 should be 50" in errs
    assert "row 6 Feb: 110 should be 112" in errs


def test_original_sample_has_bad_dates() -> None:
    assert len(check_dates(read_csv(APP1))) == 5


def test_fixed_sample_is_clean() -> None:
    assert check_totals(FIXED) == []
    assert check_dates(FIXED) == []


def test_shape_checks() -> None:
    assert check_shape(FIXED, FIXED) == []
    assert check_shape(FIXED, FIXED[:-1])
    assert check_shape(FIXED, [r[:-1] for r in FIXED])


def test_unapplied_patch_detected() -> None:
    p = Patch(row=1, column="Date", old="03/04/2026", new="05-MAR-2026", reason="x")
    errs = validate_merge(FIXED, FIXED, [p], MergeReport())
    assert any("expected '05-MAR-2026'" in e for e in errs)


def test_conflict_listed_is_accepted() -> None:
    p = Patch(row=1, column="Date", old="03/04/2026", new="05-MAR-2026", reason="x")
    rep = MergeReport(conflicts=[{"row": 1, "column": "Date"}])
    assert validate_merge(FIXED, FIXED, [p], rep) == []


def test_find_conflicts() -> None:
    a = Patch(row=2, column="Total", old="80", new="75", reason="r")
    b = Patch(row=2, column="Total", old="80", new="76", reason="r")
    c = Patch(row=3, column="Total", old="1", new="2", reason="r")
    assert find_conflicts([[a, c], [b]]) == {(2, "Total")}
    assert find_conflicts([[a], [a]]) == set()


def test_unverifiable_date_is_skipped() -> None:
    rows = [r[:] for r in FIXED]
    rows[1][0] = "TBD"
    assert check_dates(rows)
    assert check_dates(rows, {(1, "Date")}) == []


def test_expected_fixture_is_clean_and_same_shape_as_app1() -> None:
    expected = read_csv(FIXTURES / "expected_app1.csv")
    assert check_totals(expected) == []
    assert check_dates(expected) == []
    assert check_shape(read_csv(REAL), expected) == []


def test_app1_is_25_lines_with_seeded_errors() -> None:
    rows = read_csv(REAL)
    assert len(rows) == 25                      # header + 23 data rows + TOTAL
    assert len(check_dates(rows)) == 23         # every date needs normalising
    # 3 wrong row Totals, 3 wrong row Avgs, 2 wrong TOTAL-row cells
    assert len(check_totals(rows)) == 8
