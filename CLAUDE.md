# Project 1: Coordinator + 3 subagents CSV app

## Requirements

- R1: All files live under `~/Training/CCAF/project1`. The virtual environment lives at `~/Training/.venv`, outside the project and outside Documents.
- R2: A coordinator agent reads `~/Training/CCAF/project1/app1.csv` (fewer than 10 columns, about 25 rows). The file holds raw data plus calculated sum and average values for rows and columns.
- R3: The coordinator launches Agent 1 and Agent 2 in parallel (both calls in a single response).
- R4: Agent 1 converts every date to `DD-MON-YYYY` (for example `04-MAR-2026`). Dates come in multiple formats. Ambiguous dates such as 11/12 are read as MM/DD and listed in a report.
- R5: Agent 2 checks every sum and average cell and corrects wrong values.
- R6: After both finish, the coordinator launches Agent 3 (an LLM agent) to merge the outputs of Agents 1 and 2. All three agents are started by the coordinator.
- R7: When Agent 3 is done, the coordinator writes `app1_updated_<YYYYMMDD_HHMMSS>.csv` to the project folder, plus a matching change log. The original `app1.csv` is never modified.
- R8: The timestamp is generated once per run by code (local time) and reused for every file of that run.

## Cell rules

- Raw data cells are never changed (except date normalisation by Agent 1).
- Calculated cells are recognised by the headers `Total` and `Avg` and by the row label `TOTAL`.
- Averages ignore blank cells (a row with two filled months averages over two).
- Results are rounded to 2 decimals.
- In the `TOTAL` row, `Total` and the raw columns are sums of the data rows. A filled `Avg` there is the mean of the data rows' `Avg` cells; a blank one is left blank.

## Date rules

- Output format is `DD-MON-YYYY` with an uppercase month abbreviation.
- Slash dates are read as MM/DD by default and listed in the report as ambiguous when both parts are <= 12.
- If the first part is > 12 it cannot be a month, so read as DD/MM and flag it.

## File naming

- Final output: `app1_updated_<YYYYMMDD_HHMMSS>.csv`, matching `^app1_updated_\d{8}_\d{6}\.csv$`.
- Change log: `app1_changelog_<YYYYMMDD_HHMMSS>.txt`, same timestamp.
- Run artifacts go in `work/<YYYYMMDD_HHMMSS>/` (patches, `merged.csv`, `manifest.json`). `work/` is not committed.

## Layout

```
project1/
├── CLAUDE.md  pytest.ini  app1.csv (protected)
├── .claude/{settings.json, rules/csv-conventions.md}
├── docs/           INSTRUCTIONS.md (setup and usage), TUTORIAL.md (design and build steps)
├── src/            main.py (coordinator run, verification, final write), agents.py (prompts),
│                   hooks.py (write guards), tools.py (parse_date, calc_stats), schemas.py, validate.py
├── tests/          unit tests, test_e2e.py (slow, real model); fixtures/ has expected_app1.csv, sample6.csv
└── work/<ts>/      per-run artifacts (not in git)
```

## Method

- Tests first, then implementation; run `pytest` before every commit. Live tests are marked `slow`: `pytest -m slow`.
- Compare live output cell for cell with `tests/fixtures/expected_app1.csv`.
- Work on a branch; commit, PR and merge only when asked.

## Documentation

- Treat `docs/INSTRUCTIONS.md` as code: update it in the same change whenever setup steps, commands, test counts, costs, file layout or behaviour it describes change.
