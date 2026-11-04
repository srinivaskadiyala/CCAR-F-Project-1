"""Entry point: runs the coordinator, verifies Agent 3's output, writes final files."""
from __future__ import annotations

import asyncio
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError
from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, HookMatcher,
                              ResultMessage, ToolResultBlock, ToolUseBlock, UserMessage, query)

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agents import AGENTS, COORDINATOR_PROMPT  # noqa: E402
from hooks import make_hooks  # noqa: E402
from schemas import (MergeReport, PatchFile, Patch, load_manifest, new_manifest,  # noqa: E402
                     save_manifest)
from tools import build_server  # noqa: E402
from validate import read_csv, validate_merge, write_csv  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "app1.csv"
SUBAGENT_TOOLS = {"Task", "Agent"}
STAGE_AGENTS = {"agent1_dates", "agent2_math"}
SEQUENTIAL_NOTE = (
    "\nOVERRIDE for this run: do NOT launch agent1_dates and agent2_math together. Launch "
    "agent1_dates, wait for it to finish, and only then launch agent2_math in a later response."
)


def make_timestamp() -> str:
    """Local-time run timestamp, generated once per run (R8)."""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def build_options(ts: str) -> ClaudeAgentOptions:
    pre, post = make_hooks(ROOT, ts)
    return ClaudeAgentOptions(
        cwd=str(ROOT),
        system_prompt=COORDINATOR_PROMPT,
        agents=AGENTS,
        mcp_servers={"csvtools": build_server()},
        allowed_tools=["Task", "Agent", "Read", "Write", "Glob",
                       "mcp__csvtools__parse_date", "mcp__csvtools__calc_stats"],
        disallowed_tools=["Bash", "Edit"],
        permission_mode="acceptEdits",
        setting_sources=["project"],
        hooks={"PreToolUse": [HookMatcher(matcher="Write|Edit", hooks=[pre])],
               "PostToolUse": [HookMatcher(matcher="Write", hooks=[post])]},
    )


def task_prompt(ts: str, sequential: bool = False) -> str:
    work = ROOT / "work" / ts
    return (
        f"Run timestamp: {ts}\n"
        f"Source CSV (read only): {SOURCE}\n"
        f"Work folder: {work}\n"
        f"Agent 1 patch path: {work / 'agent1_patch.json'}\n"
        f"Agent 2 patch path: {work / 'agent2_patch.json'}\n"
        f"Agent 3 outputs: {work / 'merged.csv'} and {work / 'merge_report.json'}\n"
        "Process the source CSV as described in your instructions."
        + (SEQUENTIAL_NOTE if sequential else "")
    )


async def run_coordinator(prompt: str, options: ClaudeAgentOptions) -> dict:
    """Stream one coordinator run; log parallel launches and elapsed time."""
    start = time.monotonic()
    stage_ids: set[str] = set()   # tool_use ids of agent1/agent2 launches
    stage_done: float | None = None
    # The SDK may emit one AssistantMessage per content block, so group
    # top-level subagent launches by the API message they came from.
    launches_by_response: dict[str, list[str]] = {}
    cost = None
    stage_start: float | None = None
    async for msg in query(prompt=prompt, options=options):
        if isinstance(msg, AssistantMessage) and msg.parent_tool_use_id is None:
            for b in msg.content:
                if isinstance(b, ToolUseBlock) and b.name in SUBAGENT_TOOLS:
                    if b.input.get("subagent_type") in STAGE_AGENTS:
                        stage_start = stage_start or time.monotonic()
                        stage_ids.add(b.id)
                    launches_by_response.setdefault(msg.message_id or msg.uuid, []).append(
                        b.input.get("subagent_type"))
        elif isinstance(msg, UserMessage) and isinstance(msg.content, list):
            for b in msg.content:
                if isinstance(b, ToolResultBlock) and b.tool_use_id in stage_ids:
                    stage_ids.discard(b.tool_use_id)
                    if not stage_ids:
                        stage_done = time.monotonic()
        elif isinstance(msg, ResultMessage):
            cost = msg.total_cost_usd
            if msg.is_error:
                print(f"[coordinator] error result: {msg.result}", file=sys.stderr)
    for names in launches_by_response.values():
        print(f"[coordinator] launched {names} in one response")
    return {"elapsed": time.monotonic() - start,
            "stage_seconds": (stage_done - stage_start) if stage_start and stage_done else None,
            "cost": cost}


def load_patches(work: Path) -> tuple[list[Patch], list[PatchFile]]:
    files = [PatchFile.model_validate_json(p.read_text())
             for p in sorted(work.glob("agent[12]_patch.json"))]
    return [p for f in files for p in f.patches], files


def verify(ts: str) -> tuple[list[str], MergeReport | None]:
    work = ROOT / "work" / ts
    merged_path, report_path = work / "merged.csv", work / "merge_report.json"
    if not merged_path.exists() or not report_path.exists():
        return ["Agent 3 did not produce merged.csv and merge_report.json"], None
    try:
        report = MergeReport.model_validate_json(report_path.read_text())
        patches, files = load_patches(work)
        errs = validate_merge(read_csv(SOURCE), read_csv(merged_path), patches, report,
                              patch_errors=[e for f in files for e in f.errors])
    except (ValidationError, ValueError, OSError, csv.Error) as exc:
        # Malformed agent output is a verification failure (retryable), not a crash.
        return [f"Could not parse agent output: {exc}"], None
    return errs, report


def merge_timing(first: dict, second: dict) -> dict:
    """Combine the timing/cost dicts of two coordinator passes (initial run + retry)."""
    def total(key: str):
        vals = [d[key] for d in (first, second) if d.get(key) is not None]
        return sum(vals) if vals else None
    return {"elapsed": total("elapsed"), "stage_seconds": total("stage_seconds"), "cost": total("cost")}


def write_changelog(ts: str, report: MergeReport, files: list[PatchFile], timing: dict) -> Path:
    lines = [f"Change log for run {ts}", f"Source: {SOURCE.name} (unchanged)", ""]
    lines.append(f"Applied changes ({len(report.applied)}):")
    for p in report.applied:
        lines.append(f"  row {p.row} {p.column}: {p.old!r} -> {p.new!r} ({p.reason})")
    lines += ["", f"Ambiguous dates read as MM/DD ({len(report.ambiguous_dates)}):"]
    lines += [f"  {a}" for a in report.ambiguous_dates]
    lines += ["", f"Conflicts, not applied ({len(report.conflicts)}):"]
    lines += [f"  {c}" for c in report.conflicts]
    lines += ["", f"Unverified cells ({len(report.unverifiable)}):"]
    lines += [f"  {u}" for u in report.unverifiable]
    lines += ["", "Flags:"] + [f"  [{f.agent}] row {fl.row}: {fl.note}"
                                for f in files for fl in f.flags]
    lines += ["", f"Elapsed seconds (coordinator run): {timing['elapsed']:.1f}"]
    path = ROOT / f"app1_changelog_{ts}.txt"
    path.write_text("\n".join(lines) + "\n")
    return path


async def main(sequential: bool = False) -> int:
    ts = make_timestamp()
    work = ROOT / "work" / ts
    work.mkdir(parents=True)
    manifest_path = work / "manifest.json"
    save_manifest(manifest_path, new_manifest(ts))
    options = build_options(ts)

    timing = await run_coordinator(task_prompt(ts, sequential), options)
    errs, report = verify(ts)
    if errs:
        print(f"[verify] {len(errs)} problem(s); asking coordinator to fix once:")
        for e in errs:
            print("  -", e)
        retry = (task_prompt(ts, sequential) + "\nThe merged file failed verification with these errors. "
                 "Re-invoke the responsible agent(s) once, passing these errors, then re-run "
                 "agent3_merge:\n" + "\n".join(f"- {e}" for e in errs))
        timing = merge_timing(timing, await run_coordinator(retry, options))
        errs, report = verify(ts)

    manifest = load_manifest(manifest_path)
    for name, state in manifest.agents.items():
        if state.status == "pending" and manifest.agents["agent3"].status == "done":
            state.status = "skipped"
    manifest.parallel_seconds = timing["stage_seconds"]
    if errs or report is None:
        save_manifest(manifest_path, manifest)
        print("[verify] still failing; no final files written:", *errs, sep="\n  - ", file=sys.stderr)
        return 1

    _, files = load_patches(work)
    rows = read_csv(work / "merged.csv")
    final = ROOT / f"app1_updated_{ts}.csv"
    write_csv(final, rows)
    log = write_changelog(ts, report, files, timing)
    save_manifest(manifest_path, manifest)
    print(json.dumps({"final": final.name, "changelog": log.name, **timing}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sequential="--sequential" in sys.argv)))
