"""End-to-end run against the real model. Needs ANTHROPIC_API_KEY; costs money.

Run with:  pytest -m slow tests/test_e2e.py
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from validate import read_csv  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FINAL = re.compile(r"^app1_updated_(\d{8}_\d{6})\.csv$")

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY not set"),
]

EXPECTED = ROOT / "tests" / "fixtures" / "expected_app1.csv"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def run():
    def outputs() -> set[str]:
        return {m.group(1) for p in ROOT.iterdir() if (m := FINAL.match(p.name))}

    before = sha(ROOT / "app1.csv")
    existing = outputs()
    proc = subprocess.run([sys.executable, str(ROOT / "src" / "main.py")],
                          capture_output=True, text=True, cwd=ROOT, timeout=580)
    stamps = outputs() - existing
    yield proc, before, stamps
    for ts in stamps:  # remove the run's outputs from the project folder
        for name in (f"app1_updated_{ts}.csv", f"app1_changelog_{ts}.txt"):
            (ROOT / name).unlink(missing_ok=True)


def test_pipeline_matches_expected_table(run) -> None:
    proc, before, stamps = run
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert len(stamps) == 1, "exactly one run's output expected"
    ts = next(iter(stamps))  # don't mutate: the fixture deletes these on teardown

    rows = read_csv(ROOT / f"app1_updated_{ts}.csv")
    expected = read_csv(EXPECTED)
    wrong = [(r, c, got, want)
             for r, (got_row, want_row) in enumerate(zip(rows, expected))
             for c, (got, want) in enumerate(zip(got_row, want_row)) if got != want]
    assert len(rows) == len(expected), f"row count {len(rows)} != {len(expected)}"
    assert not wrong, f"cells differing from expected (row, col, got, want): {wrong}"

    assert (ROOT / f"app1_changelog_{ts}.txt").exists()
    assert (ROOT / "work" / ts / "manifest.json").exists()
    assert sha(ROOT / "app1.csv") == before, "original app1.csv was modified"


def test_agents_1_and_2_launched_in_one_response(run) -> None:
    proc, _, _ = run
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert re.search(r"launched \[('agent1_dates', 'agent2_math'|'agent2_math', 'agent1_dates')\] in one response",
                     proc.stdout)
