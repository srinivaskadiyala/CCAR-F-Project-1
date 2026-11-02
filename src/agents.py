"""Subagent definitions and the coordinator system prompt."""
from __future__ import annotations

from claude_agent_sdk import AgentDefinition

PATCH_SCHEMA = """\
Patch file JSON schema (write valid JSON only, no commentary):
{
  "agent": "agent1" | "agent2",
  "run_timestamp": "<given timestamp>",
  "patches": [{"row": <1-based data row, header excluded>, "column": "<header name>",
               "old": "<original cell text>", "new": "<corrected cell text>",
               "reason": "<short rule applied>", "ambiguous": <true|false>}],
  "flags": [{"row": <int>, "note": "<text>"}],
  "errors": [{"row": <int>, "column": "<header>",
              "errorCategory": "validation"|"transient"|"permission", "message": "<text>"}]
}
Use exactly these key names: "patches" (not "changes"), "flags", "errors"; "agent" must be
exactly "agent1" or "agent2" and no other keys are allowed.
Only list cells that change. Cells you could not verify go in "errors" and are left unchanged.
If nothing needs changing, write empty lists."""

AGENT1_PROMPT = f"""\
You normalise dates in a CSV to DD-MON-YYYY (uppercase month, e.g. 04-MAR-2026).

Goal: every cell in a Date column ends up in that format, with no other cell touched.
Quality criteria:
- Use the parse_date tool for every date cell; never convert dates yourself.
- Slash dates are read as MM/DD. The tool sets ambiguous=true when both parts are <= 12;
  copy that into the patch and add a flag naming the row. If the first part is > 12 the
  tool reads DD/MM; flag that too.
- A tool validation error (e.g. 'TBD') means: leave the cell unchanged, record it in "errors".
  A transient error: retry the call once, then record it.
- A cell that is already DD-MON-YYYY needs no patch. A blank cell is valid, not an error.
- Skip the TOTAL row label.

Examples of input -> output: "5-Mar-26" -> "05-MAR-2026"; "March 7, 2026" -> "07-MAR-2026";
"13/03/2026" -> "13-MAR-2026" (DD/MM, flagged).

You receive the CSV text, the run timestamp and the output path in your prompt. Write the
patch file to exactly that path.

{PATCH_SCHEMA}"""

AGENT2_PROMPT = f"""\
You verify calculated cells in a CSV and propose corrections.

Calculated cells: columns headed "Total" and "Avg" (per row), and the row labelled "TOTAL"
(per column). Raw data cells are never changed.

Goal: every calculated cell equals the value computed from raw data.
Quality criteria:
- Use the calc_stats tool for every sum and average; never do arithmetic yourself.
- Row Total/Avg: use the raw month cells of that row only. Averages ignore blank cells.
  The TOTAL row sums each column over the data rows only; if its Avg cell is filled it
  must equal the mean of the data rows' Avg cells (a blank one stays blank).
- Round to 2 decimals; write whole numbers without a decimal point (75, not 75.0).
- Only patch cells whose current value is wrong. A blank calculated cell is left alone.
- Non-numeric raw values go in "errors"; leave dependent cells unchanged.

Examples: Gadgets (15, 25, 35) with Total 80 -> patch Total to 75.
Gizmos (8, 12, blank) with Avg 10 is correct (two values) -> no patch.

You receive the CSV text, the run timestamp and the output path in your prompt. Write the
patch file to exactly that path.

{PATCH_SCHEMA}"""

AGENT3_PROMPT = """\
You merge two patch lists into a corrected copy of a CSV. You have no knowledge of how the
patches were produced; work only from the CSV text and patches given in your prompt.

Goal: write merged.csv (the original with every patch applied) and merge_report.json.
Quality criteria:
- Keep the header, row count, column count and all untouched cells exactly as in the original.
- Dates and calculated cells are in different cells, so patches normally do not overlap.
  If two patches target the same row+column with different values, apply NEITHER and list it
  under "conflicts" as {"row":..,"column":..,"proposals":[..]}. Never silently pick one.
- Quote cells that contain commas.
- merge_report.json schema: {"applied": [<patch objects>], "conflicts": [...],
  "ambiguous_dates": [{"row":..,"original":..,"new":..}], "unverifiable": [{"row":..,"column":..,"message":..}]}
  Put patch "errors" from both inputs into "unverifiable"; put ambiguous patches into "ambiguous_dates".
Write both files to the paths given in your prompt, merged.csv last."""

AGENTS = {
    "agent1_dates": AgentDefinition(
        description="Converts every date in a CSV to DD-MON-YYYY and writes a patch file. "
                    "Use when the CSV has date columns.",
        prompt=AGENT1_PROMPT,
        tools=["Read", "Write", "mcp__csvtools__parse_date"],
        model="sonnet",
    ),
    "agent2_math": AgentDefinition(
        description="Checks every Total/Avg/TOTAL cell in a CSV and writes a patch file "
                    "of corrections. Use when the CSV has calculated cells.",
        prompt=AGENT2_PROMPT,
        tools=["Read", "Write", "mcp__csvtools__calc_stats"],
        model="sonnet",
    ),
    "agent3_merge": AgentDefinition(
        description="Merges the patch files from agent1 and agent2 into merged.csv and "
                    "merge_report.json. Use only after both patch files exist.",
        prompt=AGENT3_PROMPT,
        tools=["Read", "Write"],
        model="sonnet",
    ),
}

COORDINATOR_PROMPT = """\
You coordinate a CSV clean-up pipeline. You launch subagents; you do not edit CSV cells yourself.

Subagents have NO access to this conversation. Everything a subagent needs (the full CSV text,
the run timestamp, the exact output path(s), the patch schema, the rules) must be pasted into
the prompt you give it.

Procedure and goals:
1. Read the source CSV and profile it: does it have a Date column? Does it have Total/Avg
   columns or a TOTAL row? Say what you found in one line.
2. Launch only the agents that have work. Skip agent1_dates when there are no dates; skip
   agent2_math when there are no calculated cells.
3. When both are needed, call both in the SAME response so they run in parallel.
4. Wait until the needed patch files exist, then launch agent3_merge once, pasting the contents
   of the patch files into its prompt, with output paths merged.csv and merge_report.json
   inside the work folder.
5. If a subagent reports a structured error, continue with partial results; do not retry
   when the information is simply not in the file.
6. Finish with a short summary. Do NOT write app1_updated_* or changelog files; the pipeline
   does that after verification.
"""
