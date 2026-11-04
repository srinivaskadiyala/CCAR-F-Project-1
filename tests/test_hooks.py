import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hooks import decide_write, make_hooks, record_write  # noqa: E402
from schemas import load_manifest, new_manifest, save_manifest  # noqa: E402

TS = "20261031_120000"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "app1.csv").write_text("Date\n")
    work = tmp_path / "work" / TS
    work.mkdir(parents=True)
    save_manifest(work / "manifest.json", new_manifest(TS))
    return tmp_path


def good_patch(agent: str) -> str:
    return json.dumps({"agent": agent, "run_timestamp": TS, "patches": [
        {"row": 1, "column": "Date", "old": "a", "new": "b", "reason": "r"}]})


def test_original_is_protected(root: Path) -> None:
    ok, reason = decide_write(str(root / "app1.csv"), root, TS)
    assert not ok and "read-only" in reason


def test_work_folder_allowed(root: Path) -> None:
    assert decide_write(str(root / "work" / TS / "agent1_patch.json"), root, TS)[0]


def test_manifest_not_writable_by_agents(root: Path) -> None:
    assert not decide_write(str(root / "work" / TS / "manifest.json"), root, TS)[0]


def test_other_paths_denied(root: Path) -> None:
    assert not decide_write(str(root / "notes.txt"), root, TS)[0]
    assert not decide_write("/etc/passwd", root, TS)[0]


def test_final_file_blocked_until_agent3_done(root: Path) -> None:
    final = root / f"app1_updated_{TS}.csv"
    ok, reason = decide_write(str(final), root, TS)
    assert not ok and "Agent 3" in reason

    work = root / "work" / TS
    (work / "merged.csv").write_text("x")
    (work / "merge_report.json").write_text("{}")
    record_write(str(work / "merged.csv"), root)
    record_write(str(work / "merge_report.json"), root)
    assert decide_write(str(final), root, TS)[0]
    assert decide_write(str(root / f"app1_changelog_{TS}.txt"), root, TS)[0]


def test_final_file_without_manifest_denied(root: Path) -> None:
    assert not decide_write(str(root / "app1_updated_20990101_000000.csv"), root, TS)[0]


def test_patch_write_marks_agent_done(root: Path) -> None:
    p = root / "work" / TS / "agent1_patch.json"
    p.write_text(good_patch("agent1"))
    assert record_write(str(p), root) is None
    m = load_manifest(root / "work" / TS / "manifest.json")
    assert m.agents["agent1"].status == "done"
    assert m.agents["agent2"].status == "pending"


def test_agent3_needs_both_files(root: Path) -> None:
    work = root / "work" / TS
    (work / "merged.csv").write_text("x")
    record_write(str(work / "merged.csv"), root)
    assert load_manifest(work / "manifest.json").agents["agent3"].status == "pending"


def test_sdk_callbacks_deny_and_allow(root: Path) -> None:
    pre, post = make_hooks(root, TS)
    deny = asyncio.run(pre({"tool_input": {"file_path": str(root / "app1.csv")}}, None, None))
    assert deny["hookSpecificOutput"]["permissionDecision"] == "deny"
    allow = asyncio.run(pre({"tool_input": {"file_path": str(root / "work" / TS / "x.json")}}, None, None))
    assert allow == {}
    assert asyncio.run(post({"tool_input": {"file_path": "nowhere.txt"}}, None, None)) == {}


OTHER = "20250101_000000"


def test_other_runs_work_folder_is_not_writable(root: Path) -> None:
    """#9: an agent must not touch artifacts of a previous run."""
    old = root / "work" / OTHER
    old.mkdir(parents=True)
    ok, reason = decide_write(str(old / "agent1_patch.json"), root, TS)
    assert not ok and OTHER in reason and TS in reason
    assert decide_write(str(root / "work" / TS / "agent1_patch.json"), root, TS)[0]


def test_final_files_of_another_run_are_denied(root: Path) -> None:
    old = root / "work" / OTHER
    old.mkdir(parents=True)
    save_manifest(old / "manifest.json", new_manifest(OTHER))
    m = load_manifest(old / "manifest.json")
    m.agents["agent3"].status = "done"
    save_manifest(old / "manifest.json", m)
    ok, reason = decide_write(str(root / f"app1_updated_{OTHER}.csv"), root, TS)
    assert not ok and "current run" in reason


# ---- strict patch schema: wrong keys must be rejected, not silently ignored ------------

def test_patch_file_with_changes_key_is_rejected_and_reported(root: Path) -> None:
    """Observed live: agents wrote 'changes' instead of 'patches'; the file must not count as done."""
    p = root / "work" / TS / "agent1_patch.json"
    p.write_text(json.dumps({"agent": "agent1", "run_timestamp": TS,
                             "changes": [{"row": 1, "column": "Date", "old": "a", "new": "b", "reason": "r"}]}))
    note = record_write(str(p), root)
    assert note and "changes" in note and "patches" in note
    assert load_manifest(root / "work" / TS / "manifest.json").agents["agent1"].status == "failed"


def test_patch_file_missing_patches_key_is_rejected(root: Path) -> None:
    p = root / "work" / TS / "agent2_patch.json"
    p.write_text(json.dumps({"agent": "agent2", "run_timestamp": TS, "flags": [], "errors": []}))
    note = record_write(str(p), root)
    assert note and "schema" in note
    assert load_manifest(root / "work" / TS / "manifest.json").agents["agent2"].status == "failed"


def test_agent_name_must_be_exact(root: Path) -> None:
    p = root / "work" / TS / "agent1_patch.json"
    p.write_text(json.dumps({"agent": "agent1_dates", "run_timestamp": TS, "patches": []}))
    assert record_write(str(p), root)


def test_empty_patches_list_is_valid(root: Path) -> None:
    p = root / "work" / TS / "agent1_patch.json"
    p.write_text(json.dumps({"agent": "agent1", "run_timestamp": TS, "patches": []}))
    assert record_write(str(p), root) is None
    assert load_manifest(root / "work" / TS / "manifest.json").agents["agent1"].status == "done"


def test_unknown_key_inside_a_patch_entry_is_rejected(root: Path) -> None:
    p = root / "work" / TS / "agent1_patch.json"
    entry = {"row": 1, "column": "Date", "old": "a", "new": "b", "reason": "r", "line": 2}
    p.write_text(json.dumps({"agent": "agent1", "run_timestamp": TS, "patches": [entry]}))
    assert record_write(str(p), root)


def test_agent_prompts_name_the_exact_keys() -> None:
    from agents import PATCH_SCHEMA
    assert '"patches"' in PATCH_SCHEMA and 'not "changes"' in PATCH_SCHEMA


def test_invalid_merge_report_marks_agent3_failed_and_explains(root: Path) -> None:
    work = root / "work" / TS
    (work / "merged.csv").write_text("x")
    (work / "merge_report.json").write_text('{"applied": 5}')
    note = record_write(str(work / "merge_report.json"), root)
    assert note and note.startswith("merge_report.json does not match the schema") and "Rewrite it" in note
    assert load_manifest(work / "manifest.json").agents["agent3"].status == "failed"
