import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tools import calc_stats, parse_date  # noqa: E402


@pytest.mark.parametrize("text,expected,ambiguous,rule", [
    ("03/04/2026", "04-MAR-2026", True, "MM/DD"),
    ("5-Mar-26", "05-MAR-2026", False, "d-Mon"),
    ("2026-03-06", "06-MAR-2026", False, "ISO"),
    ("March 7, 2026", "07-MAR-2026", False, "Month d"),
    ("13/03/2026", "13-MAR-2026", False, "DD/MM"),       # first part > 12: read as DD/MM and say so
    ("04-MAR-2026", "04-MAR-2026", False, "d-Mon"),
    ("12/25/2026", "25-DEC-2026", False, "MM/DD"),
])
def test_parse_date_valid(text: str, expected: str, ambiguous: bool, rule: str) -> None:
    r = parse_date(text)
    assert r["date"] == expected
    assert r["ambiguous"] is ambiguous
    assert rule in r["rule"]


@pytest.mark.parametrize("text", ["", "   ", None])
def test_parse_date_blank_is_valid_empty(text) -> None:
    r = parse_date(text)
    assert r["date"] is None
    assert "isError" not in r


@pytest.mark.parametrize("text", ["TBD", "31/31/2026", "2026-02-30"])
def test_parse_date_invalid_is_structured_error(text: str) -> None:
    r = parse_date(text)
    assert r["isError"] is True
    assert r["errorCategory"] == "validation"
    assert r["isRetryable"] is False
    assert r["message"]


def test_calc_stats_basic() -> None:
    assert calc_stats([15, 25, 35]) == {"sum": 75.0, "average": 25.0, "count": 3}


def test_calc_stats_ignores_blanks() -> None:
    assert calc_stats([8, 12, ""]) == {"sum": 20.0, "average": 10.0, "count": 2}


def test_calc_stats_rounds_to_two_decimals() -> None:
    assert calc_stats([1, 1, 2]) == {"sum": 4.0, "average": 1.33, "count": 3}


def test_calc_stats_all_blank_is_valid_empty() -> None:
    r = calc_stats(["", None])
    assert r["count"] == 0 and "isError" not in r


def test_calc_stats_non_numeric_is_error() -> None:
    r = calc_stats([1, "abc"])
    assert r["isError"] is True and r["errorCategory"] == "validation"


@pytest.mark.parametrize("bad", ["nan", "NaN", "inf", "-inf", "Infinity", float("nan"), float("inf")])
def test_calc_stats_rejects_non_finite(bad) -> None:
    """#10: nan/inf must be a validation error, not silently poison the sum."""
    r = calc_stats([1, bad])
    assert r["isError"] is True and r["errorCategory"] == "validation"


@pytest.mark.parametrize("bad", [True, False])
def test_calc_stats_rejects_booleans(bad) -> None:
    r = calc_stats([1, bad])
    assert r["isError"] is True and r["errorCategory"] == "validation"


def test_calc_stats_rejects_input_that_is_not_a_list() -> None:
    r = calc_stats("1,2,3")
    assert r["isError"] is True and "list" in r["message"]
