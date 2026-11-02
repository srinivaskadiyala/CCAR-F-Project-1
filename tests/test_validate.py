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


# ---- gaps found in the project review -------------------------------------------------

from validate import check_untouched  # noqa: E402


def test_total_row_avg_is_checked() -> None:
    """#1: a wrong, non-blank Avg in the TOTAL row must be flagged."""
    rows = [r[:] for r in FIXED]
    rows[6][6] = "99"                       # data-row Avgs average 22.0
    errs = check_totals(rows)
    assert any("row 6 Avg" in e for e in errs)


def test_total_row_avg_correct_or_blank_is_clean() -> None:
    rows = [r[:] for r in FIXED]
    assert check_totals(rows) == []         # blank is fine
    rows[6][6] = "22"                       # mean(20,25,10,50,5) = 22
    assert check_totals(rows) == []


def test_blank_lines_do_not_crash_checks() -> None:
    """#2: csv.reader yields [] for blank lines; checks must skip them."""
    rows = FIXED[:3] + [[]] + FIXED[3:]
    assert check_totals(rows) == []
    assert check_dates(rows) == []


def test_short_ragged_rows_do_not_crash_checks() -> None:
    rows = [r[:] for r in FIXED]
    rows[2] = rows[2][:4]                   # row with missing trailing cells
    check_totals(rows)                      # must not raise
    check_dates(rows)


def test_untouched_cells_match_original() -> None:
    assert check_untouched(FIXED, FIXED, [], MergeReport()) == []


def test_unpatched_raw_change_is_flagged() -> None:
    """#4: Agent 3 altering a raw cell without a patch must be caught."""
    merged = [r[:] for r in FIXED]
    merged[1][2] = "11"                     # Widgets Jan 10 -> 11, no patch
    errs = check_untouched(FIXED, merged, [], MergeReport())
    assert len(errs) == 1 and "row 1 Jan" in errs[0]


def test_patched_change_is_allowed_and_conflict_must_stay_original() -> None:
    original = [r[:] for r in FIXED]
    original[2][5] = "80"
    merged = [r[:] for r in FIXED]          # Gadgets Total corrected to 75
    p = Patch(row=2, column="Total", old="80", new="75", reason="sum")
    assert check_untouched(original, merged, [p], MergeReport()) == []
    rep = MergeReport(conflicts=[{"row": 2, "column": "Total"}])
    errs = check_untouched(original, merged, [p], rep)
    assert errs and "conflict" in errs[0]


def test_validate_merge_reports_untouched_changes() -> None:
    merged = [r[:] for r in FIXED]
    merged[1][2], merged[1][3] = "12", "18"   # Jan +2, Feb -2: row Total/Avg still consistent
    merged[6][2], merged[6][3] = "80", "110"  # ...and the TOTAL row follows, so only check_untouched objects
    errs = validate_merge(FIXED, merged, [], MergeReport())
    assert any("Jan" in e for e in errs) and any("Feb" in e for e in errs)
