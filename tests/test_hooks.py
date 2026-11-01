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
    ok, reason = decide_write(str(root / "app1.csv"), root)
    assert not ok and "read-only" in reason


def test_work_folder_allowed(root: Path) -> None:
    assert decide_write(str(root / "work" / TS / "agent1_patch.json"), root)[0]


def test_manifest_not_writable_by_agents(root: Path) -> None:
    assert not decide_write(str(root / "work" / TS / "manifest.json"), root)[0]


def test_other_paths_denied(root: Path) -> None:
    assert not decide_write(str(root / "notes.txt"), root)[0]
    assert not decide_write("/etc/passwd", root)[0]


def test_final_file_blocked_until_agent3_done(root: Path) -> None:
    final = root / f"app1_updated_{TS}.csv"
    ok, reason = decide_write(str(final), root)
    assert not ok and "Agent 3" in reason

    work = root / "work" / TS
    (work / "merged.csv").write_text("x")
    (work / "merge_report.json").write_text("{}")
    record_write(str(work / "merged.csv"), root)
    record_write(str(work / "merge_report.json"), root)
    assert decide_write(str(final), root)[0]
    assert decide_write(str(root / f"app1_changelog_{TS}.txt"), root)[0]


def test_final_file_without_manifest_denied(root: Path) -> None:
    assert not decide_write(str(root / "app1_updated_20990101_000000.csv"), root)[0]


def test_patch_write_marks_agent_done(root: Path) -> None:
    p = root / "work" / TS / "agent1_patch.json"
    p.write_text(good_patch("agent1"))
    assert record_write(str(p), root) is None
    m = load_manifest(root / "work" / TS / "manifest.json")
    assert m.agents["agent1"].status == "done"
    assert m.agents["agent2"].status == "pending"


def test_invalid_patch_marks_failed_and_reports(root: Path) -> None:
    p = root / "work" / TS / "agent2_patch.json"
    p.write_text('{"agent": "agent2"}')
    note = record_write(str(p), root)
    assert note and "schema" in note
    assert load_manifest(root / "work" / TS / "manifest.json").agents["agent2"].status == "failed"


def test_agent3_needs_both_files(root: Path) -> None:
    work = root / "work" / TS
    (work / "merged.csv").write_text("x")
    record_write(str(work / "merged.csv"), root)
    assert load_manifest(work / "manifest.json").agents["agent3"].status == "pending"


def test_sdk_callbacks_deny_and_allow(root: Path) -> None:
    pre, post = make_hooks(root)
    deny = asyncio.run(pre({"tool_input": {"file_path": str(root / "app1.csv")}}, None, None))
    assert deny["hookSpecificOutput"]["permissionDecision"] == "deny"
    allow = asyncio.run(pre({"tool_input": {"file_path": str(root / "work" / TS / "x.json")}}, None, None))
    assert allow == {}
    assert asyncio.run(post({"tool_input": {"file_path": "nowhere.txt"}}, None, None)) == {}
