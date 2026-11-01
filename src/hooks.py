"""PreToolUse / PostToolUse hooks that enforce file-write rules.

Decision logic lives in pure functions (``decide_write``, ``record_write``) so
tests call them directly; ``make_hooks`` wraps them as SDK hook callbacks.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from schemas import MergeReport, PatchFile, load_manifest, save_manifest

FINAL_RE = re.compile(r"^app1_(?:updated_(\d{8}_\d{6})\.csv|changelog_(\d{8}_\d{6})\.txt)$")
PATCH_FILES = {"agent1_patch.json": "agent1", "agent2_patch.json": "agent2"}


def _work_parts(path: Path, root: Path) -> tuple[str, str] | None:
    """Return (timestamp, filename) if path is directly inside work/<ts>/."""
    try:
        rel = path.resolve().relative_to((root / "work").resolve())
    except ValueError:
        return None
    return (rel.parts[0], rel.parts[1]) if len(rel.parts) == 2 else None


def decide_write(file_path: str, root: Path) -> tuple[bool, str]:
    """Return (allowed, reason) for a Write/Edit to file_path."""
    path = Path(file_path).expanduser()
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    root = root.resolve()

    if path == root / "app1.csv":
        return False, "app1.csv is the protected original and is read-only."

    work = _work_parts(path, root)
    if work:
        if work[1] == "manifest.json":
            return False, "manifest.json is maintained by the pipeline, not by agents."
        return True, "inside the run's work folder"

    m = FINAL_RE.match(path.name)
    if path.parent == root and m:
        ts = m.group(1) or m.group(2)
        manifest = root / "work" / ts / "manifest.json"
        if not manifest.exists():
            return False, f"no manifest for run {ts}; cannot write final files."
        if load_manifest(manifest).agents["agent3"].status != "done":
            return False, "Agent 3 (merge) has not finished; final files cannot be written yet."
        return True, "agent3 is done"

    return False, f"writes are only allowed in work/<timestamp>/ or as final app1_* files, not {path}"


def record_write(file_path: str, root: Path) -> str | None:
    """After a successful Write, update the manifest. Returns a note on problems."""
    path = Path(file_path).expanduser()
    if not path.is_absolute():
        path = root / path
    work = _work_parts(path, root)
    if not work:
        return None
    ts, name = work
    manifest_path = root / "work" / ts / "manifest.json"
    if not manifest_path.exists():
        return None
    manifest = load_manifest(manifest_path)
    note: str | None = None

    if name in PATCH_FILES:
        agent = PATCH_FILES[name]
        try:
            PatchFile.model_validate_json(path.read_text())
            manifest.agents[agent].status = "done"
            manifest.agents[agent].files = [str(path)]
        except (ValidationError, ValueError) as exc:
            manifest.agents[agent].status = "failed"
            note = f"{name} does not match the patch schema: {exc}. Rewrite it."
    elif name in ("merged.csv", "merge_report.json"):
        merged, report = path.parent / "merged.csv", path.parent / "merge_report.json"
        if merged.exists() and report.exists():
            try:
                MergeReport.model_validate_json(report.read_text())
                manifest.agents["agent3"].status = "done"
                manifest.agents["agent3"].files = [str(merged), str(report)]
            except (ValidationError, ValueError) as exc:
                manifest.agents["agent3"].status = "failed"
                note = f"merge_report.json does not match the schema: {exc}. Rewrite it."
    save_manifest(manifest_path, manifest)
    return note


def make_hooks(root: Path):
    """Build (pre, post) async hook callbacks bound to a project root."""

    async def pre(input_data: dict[str, Any], tool_use_id: str | None, context: Any) -> dict[str, Any]:
        file_path = input_data.get("tool_input", {}).get("file_path", "")
        allowed, reason = decide_write(file_path, root)
        if allowed:
            return {}
        return {"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason}}

    async def post(input_data: dict[str, Any], tool_use_id: str | None, context: Any) -> dict[str, Any]:
        file_path = input_data.get("tool_input", {}).get("file_path", "")
        note = record_write(file_path, root)
        if note:
            return {"hookSpecificOutput": {
                "hookEventName": "PostToolUse", "additionalContext": note}}
        return {}

    return pre, post
