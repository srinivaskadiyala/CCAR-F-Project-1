"""Entry point: runs the coordinator, verifies Agent 3's output, writes final files."""
from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, HookMatcher,
                              ResultMessage, ToolUseBlock, query)

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


def make_timestamp() -> str:
    """Local-time run timestamp, generated once per run (R8)."""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def build_options(ts: str) -> ClaudeAgentOptions:
    pre, post = make_hooks(ROOT)
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


def task_prompt(ts: str) -> str:
    work = ROOT / "work" / ts
    return (
        f"Run timestamp: {ts}\n"
        f"Source CSV (read only): {SOURCE}\n"
        f"Work folder: {work}\n"
        f"Agent 1 patch path: {work / 'agent1_patch.json'}\n"
        f"Agent 2 patch path: {work / 'agent2_patch.json'}\n"
        f"Agent 3 outputs: {work / 'merged.csv'} and {work / 'merge_report.json'}\n"
        "Process the source CSV as described in your instructions."
    )


async def run_coordinator(prompt: str, options: ClaudeAgentOptions) -> dict:
    """Stream one coordinator run; log parallel launches and elapsed time."""
    start = time.monotonic()
    first_launch = None
    # The SDK may emit one AssistantMessage per content block, so group
    # top-level subagent launches by the API message they came from.
    launches_by_response: dict[str, list[str]] = {}
    cost = None
    async for msg in query(prompt=prompt, options=options):
        if isinstance(msg, AssistantMessage) and msg.parent_tool_use_id is None:
            for b in msg.content:
                if isinstance(b, ToolUseBlock) and b.name in SUBAGENT_TOOLS:
                    first_launch = first_launch or time.monotonic()
                    launches_by_response.setdefault(msg.message_id or msg.uuid, []).append(
                        b.input.get("subagent_type"))
        elif isinstance(msg, ResultMessage):
            cost = msg.total_cost_usd
            if msg.is_error:
                print(f"[coordinator] error result: {msg.result}", file=sys.stderr)
    for names in launches_by_response.values():
        print(f"[coordinator] launched {names} in one response")
    return {"elapsed": time.monotonic() - start,
            "since_first_launch": (time.monotonic() - first_launch) if first_launch else None,
            "launch_sizes": [len(v) for v in launches_by_response.values()], "cost": cost}


def load_patches(work: Path) -> tuple[list[Patch], list[PatchFile]]:
    files = [PatchFile.model_validate_json(p.read_text())
             for p in sorted(work.glob("agent[12]_patch.json"))]
    return [p for f in files for p in f.patches], files


def verify(ts: str) -> tuple[list[str], MergeReport | None]:
    work = ROOT / "work" / ts
    merged_path, report_path = work / "merged.csv", work / "merge_report.json"
    if not merged_path.exists() or not report_path.exists():
        return ["Agent 3 did not produce merged.csv and merge_report.json"], None
    report = MergeReport.model_validate_json(report_path.read_text())
    patches, _ = load_patches(work)
    errs = validate_merge(read_csv(SOURCE), read_csv(merged_path), patches, report)
    return errs, report


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


async def main() -> int:
    ts = make_timestamp()
    work = ROOT / "work" / ts
    work.mkdir(parents=True)
    manifest_path = work / "manifest.json"
    save_manifest(manifest_path, new_manifest(ts))
    options = build_options(ts)

    timing = await run_coordinator(task_prompt(ts), options)
    errs, report = verify(ts)
    if errs:
        print(f"[verify] {len(errs)} problem(s); asking coordinator to fix once:")
        for e in errs:
            print("  -", e)
        retry = (task_prompt(ts) + "\nThe merged file failed verification with these errors. "
                 "Re-invoke the responsible agent(s) once, passing these errors, then re-run "
                 "agent3_merge:\n" + "\n".join(f"- {e}" for e in errs))
        timing = await run_coordinator(retry, options)
        errs, report = verify(ts)

    manifest = load_manifest(manifest_path)
    for name, state in manifest.agents.items():
        if state.status == "pending" and manifest.agents["agent3"].status == "done":
            state.status = "skipped"
    manifest.parallel_seconds = timing["since_first_launch"]
    if errs or report is None:
        save_manifest(manifest_path, manifest)
        print("[verify] still failing; no final files written:", *errs, sep="\n  - ", file=sys.stderr)
        return 1

    _, files = load_patches(work)
    rows = read_csv(work / "merged.csv")
    final = ROOT / f"app1_updated_{ts}.csv"
    write_csv(final, rows)
    log = write_changelog(ts, report, files, timing)
    manifest.final_files = [final.name, log.name]
    save_manifest(manifest_path, manifest)
    print(json.dumps({"final": final.name, "changelog": log.name, **timing}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
