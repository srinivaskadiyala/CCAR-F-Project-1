"""Deterministic CSV tools: date parsing and sum/average statistics.

The plain functions are unit-tested directly; thin @tool wrappers expose them
to agents through the in-process MCP server ``csvtools``.
"""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
          "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
_MONTH_LOOKUP = {m: i + 1 for i, m in enumerate(MONTHS)}
_MONTH_LOOKUP.update({
    "JANUARY": 1, "FEBRUARY": 2, "MARCH": 3, "APRIL": 4, "JUNE": 6, "JULY": 7,
    "AUGUST": 8, "SEPTEMBER": 9, "SEPT": 9, "OCTOBER": 10, "NOVEMBER": 11,
    "DECEMBER": 12,
})


def _error(category: str, message: str, retryable: bool = False) -> dict[str, Any]:
    return {"isError": True, "errorCategory": category,
            "isRetryable": retryable, "message": message}


def _format(y: int, m: int, d: int) -> str | None:
    try:
        date(y, m, d)
    except ValueError:
        return None
    return f"{d:02d}-{MONTHS[m - 1]}-{y:04d}"


def _year(text: str) -> int:
    y = int(text)
    return 2000 + y if len(text) <= 2 else y


def parse_date(text: str | None) -> dict[str, Any]:
    """Convert one date string to DD-MON-YYYY.

    Returns {"date", "ambiguous", "rule"} on success, {"date": None, "rule":
    "empty"} for blank input (a valid empty result), or a structured validation
    error when the text is not a recognisable date.
    """
    if text is None or not text.strip():
        return {"date": None, "ambiguous": False, "rule": "empty"}
    s = text.strip()

    # Already DD-MON-YYYY, or D-Mon-YY / D Mon YYYY
    m = re.fullmatch(r"(\d{1,2})[-\s]([A-Za-z]{3,9})[-\s,]*(\d{2}|\d{4})", s)
    if m and m.group(2).upper() in _MONTH_LOOKUP:
        out = _format(_year(m.group(3)), _MONTH_LOOKUP[m.group(2).upper()], int(m.group(1)))
        if out:
            return {"date": out, "ambiguous": False, "rule": "d-Mon-y"}

    # March 7, 2026
    m = re.fullmatch(r"([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})", s)
    if m and m.group(1).upper() in _MONTH_LOOKUP:
        out = _format(int(m.group(3)), _MONTH_LOOKUP[m.group(1).upper()], int(m.group(2)))
        if out:
            return {"date": out, "ambiguous": False, "rule": "Month d, yyyy"}

    # ISO 2026-03-06
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        out = _format(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if out:
            return {"date": out, "ambiguous": False, "rule": "ISO yyyy-mm-dd"}

    # Slash dates: MM/DD by default, DD/MM when the first part cannot be a month
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})", s)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), _year(m.group(3))
        if a > 12:
            out = _format(y, b, a)
            if out:
                return {"date": out, "ambiguous": False, "rule": "DD/MM (first part > 12)"}
        else:
            out = _format(y, a, b)
            if out:
                return {"date": out, "ambiguous": b <= 12, "rule": "MM/DD default"}

    return _error("validation", f"Unrecognised or invalid date: {text!r}")


def calc_stats(values: list[Any]) -> dict[str, Any]:
    """Sum and average of numeric values, ignoring blanks, rounded to 2 decimals."""
    if not isinstance(values, list):
        return _error("validation", "values must be a list")
    nums: list[float] = []
    for v in values:
        if v is None or (isinstance(v, str) and not v.strip()):
            continue
        try:
            nums.append(float(v))
        except (TypeError, ValueError):
            return _error("validation", f"Non-numeric value: {v!r}")
    if not nums:
        return {"sum": 0.0, "average": None, "count": 0}
    total = sum(nums)
    return {"sum": round(total, 2), "average": round(total / len(nums), 2),
            "count": len(nums)}


def _wrap(result: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"content": [{"type": "text", "text": json.dumps(result)}]}
    if result.get("isError"):
        out["isError"] = True
    return out


@tool(
    "parse_date",
    "Convert ONE date string to DD-MON-YYYY (e.g. 04-MAR-2026). Accepts MM/DD/YYYY "
    "(read as MM/DD by default; 'ambiguous' is true when both parts are <= 12), "
    "DD/MM/YYYY only when the first part is > 12, YYYY-MM-DD, 'March 7, 2026', "
    "'5-Mar-26'. Blank input returns date null (valid, not an error). Unparseable "
    "text such as 'TBD' returns a validation error; leave that cell unchanged. "
    "Do NOT use for numbers or for text that is not a date.",
    {"text": str},
)
async def parse_date_tool(args: dict[str, Any]) -> dict[str, Any]:
    return _wrap(parse_date(args.get("text")))


@tool(
    "calc_stats",
    "Compute sum, average and count of a list of numbers, ignoring blank cells, "
    "rounded to 2 decimals. Pass raw cell values for ONE row or column, excluding "
    "the Total/Avg cells themselves. Example: [10, 20, ''] -> sum 30, average 15, "
    "count 2. Non-numeric values return a validation error. Do NOT use for dates.",
    {"values": list},
)
async def calc_stats_tool(args: dict[str, Any]) -> dict[str, Any]:
    return _wrap(calc_stats(args.get("values", [])))


def build_server():
    return create_sdk_mcp_server("csvtools", tools=[parse_date_tool, calc_stats_tool])
