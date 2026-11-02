import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import main  # noqa: E402
from schemas import Patch, MergeReport  # noqa: E402
from validate import check_patches_accounted, read_csv  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
TS = "20261031_120000"


def write_patches(source: Path, expected: Path, work: Path) -> None:
    """Write a patch file explaining every difference between source and expected."""
    src, exp = read_csv(source), read_csv(expected)
    patches = [{"row": r, "column": src[0][c], "old": src[r][c], "new": exp[r][c], "reason": "test"}
               for r in range(1, len(src)) for c in range(len(src[0])) if src[r][c] != exp[r][c]]
    (work / "agent1_patch.json").write_text(json.dumps(
        {"agent": "agent1", "run_timestamp": TS, "patches": patches}))


@pytest.fixture
def run_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fake project root with the 25-line source and a correct merged.csv."""
    shutil.copy(Path(main.ROOT) / "app1.csv", tmp_path / "app1.csv")
    work = tmp_path / "work" / TS
    work.mkdir(parents=True)
    shutil.copy(FIXTURES / "expected_app1.csv", work / "merged.csv")
    (work / "merge_report.json").write_text(MergeReport().model_dump_json())
    write_patches(tmp_path / "app1.csv", FIXTURES / "expected_app1.csv", work)
    monkeypatch.setattr(main, "ROOT", tmp_path)
    monkeypatch.setattr(main, "SOURCE", tmp_path / "app1.csv")
    return work


def test_verify_accepts_a_correct_merge(run_dir: Path) -> None:
    errs, report = main.verify(TS)
    assert errs == [] and report is not None


def test_verify_missing_outputs_is_an_error(run_dir: Path) -> None:
    (run_dir / "merged.csv").unlink()
    errs, report = main.verify(TS)
    assert errs and report is None


@pytest.mark.parametrize("name,content", [
    ("merge_report.json", '{"applied": "not a list"'),          # truncated JSON
    ("merge_report.json", '{"applied": 5}'),                    # wrong schema
    ("agent1_patch.json", '{"agent": "agent1"}'),               # patch missing fields
])
def test_verify_malformed_agent_output_is_retryable_not_a_crash(run_dir: Path, name: str, content: str) -> None:
    (run_dir / name).write_text(content)
    errs, report = main.verify(TS)          # must not raise
    assert report is None
    assert len(errs) == 1 and "Could not parse agent output" in errs[0]


def test_patch_row_out_of_range_is_reported_not_a_crash() -> None:
    rows = read_csv(FIXTURES / "expected_app1.csv")
    bad = [Patch(row=99, column="Date", old="x", new="y", reason="r"),
           Patch(row=0, column="Date", old="x", new="y", reason="r")]
    errs = check_patches_accounted(rows, rows, bad, MergeReport())
    assert len(errs) == 2 and all("out of range" in e for e in errs)


def test_merge_timing_sums_both_passes() -> None:
    first = {"elapsed": 100.0, "stage_seconds": 10.0, "since_first_launch": 90.0,
             "launch_sizes": [2, 1], "cost": 0.5}
    retry = {"elapsed": 60.0, "stage_seconds": None, "since_first_launch": 50.0,
             "launch_sizes": [1], "cost": 0.25}
    t = main.merge_timing(first, retry)
    assert t == {"elapsed": 160.0, "stage_seconds": 10.0, "since_first_launch": 140.0,
                 "launch_sizes": [2, 1, 1], "cost": 0.75}


def test_merge_timing_none_cost_stays_none() -> None:
    a = {"elapsed": 1.0, "stage_seconds": None, "since_first_launch": None,
         "launch_sizes": [], "cost": None}
    assert main.merge_timing(a, a)["cost"] is None
    assert main.merge_timing(a, a)["stage_seconds"] is None


def test_settings_json_uses_only_edit_rules() -> None:
    cfg = json.loads((Path(main.ROOT) / ".claude" / "settings.json").read_text())
    rules = cfg["permissions"]["allow"] + cfg["permissions"]["deny"]
    assert all(r.startswith(("Edit(", "Read(")) for r in rules)
    assert any("app1.csv" in r for r in cfg["permissions"]["deny"])


def test_main_retries_once_and_combines_timing(run_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Drive main() with a fake coordinator: first pass writes garbage, retry writes a good merge."""
    import asyncio
    from schemas import load_manifest, save_manifest

    root = main.ROOT
    shutil.rmtree(root / "work")                      # main() creates its own work folder
    monkeypatch.setattr(main, "make_timestamp", lambda: TS)
    calls: list[str] = []

    async def fake(prompt: str, options) -> dict:
        calls.append(prompt)
        work = root / "work" / TS
        shutil.copy(FIXTURES / "expected_app1.csv", work / "merged.csv")
        write_patches(root / "app1.csv", FIXTURES / "expected_app1.csv", work)
        good = len(calls) > 1
        (work / "merge_report.json").write_text(MergeReport().model_dump_json() if good else "{broken")
        manifest = load_manifest(work / "manifest.json")
        manifest.agents["agent3"].status = "done"
        save_manifest(work / "manifest.json", manifest)
        return {"elapsed": 100.0 if not good else 60.0, "stage_seconds": 10.0 if not good else None,
                "since_first_launch": 90.0, "launch_sizes": [2], "cost": 0.5}

    monkeypatch.setattr(main, "run_coordinator", fake)
    assert asyncio.run(main.main()) == 0
    assert len(calls) == 2 and "failed verification" in calls[1]
    assert (root / f"app1_updated_{TS}.csv").exists()
    assert "Elapsed seconds (coordinator run): 160.0" in (root / f"app1_changelog_{TS}.txt").read_text()
    assert load_manifest(root / "work" / TS / "manifest.json").parallel_seconds == 10.0


def test_verify_csv_error_is_retryable_not_a_crash(run_dir: Path) -> None:
    """#6: csv.Error (not a ValueError) from a malformed merged.csv must not crash."""
    (run_dir / "merged.csv").write_text("Date,Item\n" + "x" * 200_000 + ",y\n")   # > csv field limit
    errs, report = main.verify(TS)
    assert report is None
    assert len(errs) == 1 and "Could not parse agent output" in errs[0]


def test_verify_blank_line_in_merged_is_an_error_not_a_crash(run_dir: Path) -> None:
    (run_dir / "merged.csv").write_text((FIXTURES / "expected_app1.csv").read_text() + "\n")
    errs, _ = main.verify(TS)
    assert errs                              # row count differs, reported cleanly
