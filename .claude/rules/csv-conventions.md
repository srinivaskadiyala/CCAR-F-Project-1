---
paths: ["**/*.csv", "tests/**"]
---

# CSV conventions

- Never modify `app1.csv`; write results to `app1_updated_<YYYYMMDD_HHMMSS>.csv`.
- Dates are `DD-MON-YYYY` (e.g. `04-MAR-2026`). Slash dates are MM/DD unless the first part is > 12.
- In the TOTAL row, a filled Avg is the mean of the data rows' Avg cells; blank stays blank.
- Calculated cells: headers `Total` and `Avg`, and row label `TOTAL`. Averages ignore blanks; round to 2 decimals.
- Preserve row count, column count, header names and quoting when rewriting.
- Tests on dates and totals assert exact values, since this logic is deterministic.
