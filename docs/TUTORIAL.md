# Tutorial: Build a Coordinator + 3 Subagents CSV App with Claude Code (Vibe Coding)

Purpose: hands-on practice for the CCAR-F exam. The app is small on purpose, but every step is tied to an exam objective, with extra attention to the areas that scored low on the October 28, 2026 score report (parallel tool calls, dynamic decomposition, state persistence, configuration mechanism selection, context optimization, tool_choice sequencing, plan mode vs direct execution).

Estimated time: 3 to 5 hours, spread over a few sessions.

---

## 0. Requirements (final)

| # | Requirement |
|---|---|
| R1 | All files live under `~/Training/CCAF/project1`. The virtual environment lives at `~/Training/.venv`, outside the project and outside Documents. |
| R2 | A coordinator agent reads `~/Training/CCAF/project1/app1.csv` (fewer than 10 columns, about 25 rows). The file holds raw data plus calculated sum and average values for rows and columns. |
| R3 | The coordinator launches Agent 1 and Agent 2 in parallel (both calls in a single response). |
| R4 | Agent 1 converts every date to `DD-MON-YYYY` (for example `04-MAR-2026`). Dates come in multiple formats. Ambiguous dates such as 11/12 are read as MM/DD and listed in a report. |
| R5 | Agent 2 checks every sum and average cell and corrects wrong values. |
| R6 | After both finish, the coordinator launches Agent 3 (an LLM agent) to merge the outputs of Agents 1 and 2. All three agents are started by the coordinator. |
| R7 | When Agent 3 is done, the coordinator writes `app1_updated_<YYYYMMDD_HHMMSS>.csv` to the project folder, plus a matching change log. The original `app1.csv` is never modified. |
| R8 | The timestamp is generated once per run by code (local time) and reused for every file of that run. |

## 1. Design decisions (why the prompt was changed)

1. **Three subagents, not two.** The original text said two but described three. The design has one coordinator plus Agents 1, 2 and 3.
2. **Patches, not whole files.** Agents 1 and 2 touch different cells, so each returns a list of cell changes. Agent 3 merges the lists and applies them. This avoids two competing rewrites of the same file.
3. **Deterministic work goes into tools.** Date parsing and arithmetic are done by small custom tools. The agents decide which cells to examine and why, and the tools compute the values.
4. **Hub and spoke.** Subagents never talk to each other. The coordinator passes everything each subagent needs in its prompt, because subagents do not inherit context.
5. **Hooks enforce what must never fail.** The original file is protected and the final file cannot be written until Agent 3 is done. A prompt instruction alone has a non-zero failure rate.
6. **Dynamic decomposition.** The coordinator profiles the CSV first and skips Agent 1 or Agent 2 when there is nothing for them to do.

### Architecture

```
                       main.py (Python, no LLM)
        creates run timestamp, work folder, manifest, hooks
                              |
                        COORDINATOR
         (tools: Agent/Task, Read, Write, Glob)
                              |
            profile CSV -> decide which agents are needed
                              |
          +-------------------+-------------------+
          |  one response, two parallel calls     |
      AGENT 1 (dates)                        AGENT 2 (math)
      Read, Write,                           Read, Write,
      parse_date tool                        calc_stats tool
          |                                       |
   work/<ts>/agent1_patch.json          work/<ts>/agent2_patch.json
          +-------------------+-------------------+
                              |
                  AGENT 3 (merge, fresh context)
                  Read, Write
                              |
          work/<ts>/merged.csv + merge_report.json
                              |
                  COORDINATOR validates, then writes
          app1_updated_<ts>.csv + app1_changelog_<ts>.txt
```

### Folder layout

```
~/Training/
├── .venv/
└── CCAF/
    ├── CLAUDE.md                  shared rules for all CCAF projects
    └── project1/
        ├── CLAUDE.md              project rules
        ├── .claude/
        │   ├── settings.json      permissions
        │   ├── rules/csv-conventions.md
        │   ├── skills/date-format-check/SKILL.md
        │   └── commands/run-pipeline.md
        ├── app1.csv
        ├── src/  (main.py, agents.py, tools.py, hooks.py)
        ├── tests/
        └── work/<timestamp>/      patches, merged.csv, manifest.json
```

## 2. Sample data (use this to start, then replace with your real file)

Create `app1.csv`. It has seeded errors so you know what the correct result must be.

```
Date,Item,Jan,Feb,Mar,Total,Avg
03/04/2026,Widgets,10,20,30,60,20
5-Mar-26,Gadgets,15,25,35,80,25
2026-03-06,Gizmos,8,12,,20,10
"March 7, 2026",Doohickeys,40,50,60,150,55
13/03/2026,Thingamajigs,5,5,5,15,5
TOTAL,,78,110,130,320,
```

Expected results:

| Cell | Before | After | Reason |
|---|---|---|---|
| Row 1 date | 03/04/2026 | 04-MAR-2026 | MM/DD rule, listed as ambiguous |
| Row 2 date | 5-Mar-26 | 05-MAR-2026 | |
| Row 3 date | 2026-03-06 | 06-MAR-2026 | |
| Row 4 date | March 7, 2026 | 07-MAR-2026 | |
| Row 5 date | 13/03/2026 | 13-MAR-2026 | Month 13 is impossible, so read as DD/MM and flagged |
| Gadgets Total | 80 | 75 | 15+25+35 |
| Doohickeys Avg | 55 | 50 | 150 / 3 |
| TOTAL row, Feb | 110 | 112 | 20+25+12+50+5 |

Rules to put in CLAUDE.md: averages ignore blank cells (Gizmos Avg is 10 because two months have values), results round to 2 decimals, raw data cells are never changed, calculated cells are recognised by the headers `Total` and `Avg` and by the row label `TOTAL`.

## 3. Vibe coding method used in every step

1. State intent and constraints in plain language, not code.
2. Let Claude Code propose first (plan mode for anything touching more than one file).
3. Run what it built. Share the real error or wrong output back, with a concrete input and expected output.
4. Commit to git after each working step so any step can be undone.
5. Read the diff before accepting it. You are the reviewer.

Keep each prompt small. Fix interacting problems in one message, independent problems one at a time.

---

## 4. Steps

### Step 1. Environment setup (about 15 minutes)

```bash
mkdir -p ~/Training/CCAF/project1
cd ~/Training
python3 -m venv .venv
source .venv/bin/activate
pip install claude-agent-sdk pytest pydantic
cd ~/Training/CCAF/project1
git init
```

- Install Claude Code if needed: `curl -fsSL https://claude.ai/install.sh | bash`
- Set the API key as an environment variable in your shell profile, never in a file inside the repo: `export ANTHROPIC_API_KEY=...`
- Add `work/`, `*.pyc` and `.env` to `.gitignore`.
- Always activate the venv, then start Claude Code from `~/Training/CCAF/project1`.

Check: `python -c "import claude_agent_sdk"` runs without error, and `claude` starts in the project folder.

### Step 2. Configure Claude Code (CLAUDE.md hierarchy, rules, permissions)

Exam objectives: 3.1, 3.3, configuration mechanism selection.

Start Claude Code and ask it to create these files (review each one):

1. `~/Training/CCAF/CLAUDE.md`: shared conventions only (Python 3.10+, type hints, pytest, never commit secrets, work inside `~/Training/CCAF`).
2. `~/Training/CCAF/project1/CLAUDE.md`: the requirements R1 to R8, the cell rules from section 2, the MM/DD rule, and the file naming convention.
3. `.claude/rules/csv-conventions.md` with YAML frontmatter `paths: ["**/*.csv", "tests/**"]` so the CSV conventions load only when working on those files.
4. `.claude/settings.json`: allow reads and writes only under `~/Training/CCAF`, deny edits to `app1.csv`.

Prompt:

```
Create the CLAUDE.md files and the path-scoped rule file for this project
as described in TUTORIAL section 2 and 4. Put universal rules in CLAUDE.md,
CSV-only conventions in .claude/rules with a paths glob, and permission
limits in settings.json. Show me each file before writing.
```

Check with `/memory` that both CLAUDE.md files are loaded. Open a `.csv` file and confirm the rule file appears when relevant.

Think about the choice: why is the CSV convention a path-scoped rule and not a skill? (Rules load automatically by file pattern; skills need to be invoked.)

### Step 3. Plan the architecture (plan mode)

Exam objectives: 3.4, plan mode vs direct execution.

Switch to plan mode (Shift+Tab) and give the requirements:

```
Plan the implementation of the app described in CLAUDE.md. Do not write
code yet. Cover: module layout, the patch JSON schema, the manifest
schema, which tools each agent gets, which hooks are needed, and a test
plan. Ask me questions if anything is ambiguous (interview me first).
```

Review the plan against sections 1 and 5 of this tutorial. Approve, then exit plan mode. Write down: why plan mode here, and why direct execution later for small fixes like a typo in a prompt.

### Step 4. Patch schema and tools

Exam objectives: 2.1, 2.2, 4.3.

Define the contract before the agents. Patch format (JSON):

```json
{
  "agent": "agent1",
  "run_timestamp": "20261030_174900",
  "patches": [
    {"row": 2, "column": "Date", "old": "5-Mar-26", "new": "05-MAR-2026",
     "reason": "parsed d-Mon-yy", "ambiguous": false}
  ],
  "flags": [{"row": 1, "note": "03/04/2026 read as MM/DD"}],
  "errors": []
}
```

Prompt:

```
Create src/tools.py with two in-process MCP tools using the SDK:
1. parse_date(text): returns DD-MON-YYYY, a flag if the input was ambiguous
   (both parts <= 12), and the rule applied. Month > 12 in the first part
   means DD/MM. Read MM/DD by default.
2. calc_stats(values): returns sum, average (ignoring blanks), count, and
   rounds to 2 decimals.
Both must return structured errors with errorCategory
(validation/transient/permission), isRetryable, and a human-readable
message, using the isError flag. An input with no date is a valid empty
result, not an error. Write detailed tool descriptions: formats accepted,
examples, and when NOT to use the tool. Add pytest tests with the cases
from section 2.
```

Run `pytest`. Feed any failure back with the exact input and expected output.

Exam notes: tool descriptions are the main selection mechanism; uniform "operation failed" errors prevent good recovery.

### Step 5. Agent definitions

Exam objectives: 1.3, 2.3, 4.1, 4.2.

Prompt:

```
Create src/agents.py with AgentDefinition objects for agent1_dates,
agent2_math, agent3_merge. Each has a description, a goal-oriented system
prompt (state the goal and quality criteria, not step-by-step procedure),
and a minimal tools list:
- agent1: Read, Write, mcp__csvtools__parse_date
- agent2: Read, Write, mcp__csvtools__calc_stats
- agent3: Read, Write (no csv tools)
Agent 1 prompt includes 3 few-shot examples of messy dates and the
ambiguous-date rule. Agent 2 prompt includes 2 examples, one with a blank
cell. All agents must write their output as the patch JSON schema.
```

Reference shape (verify field names against your installed SDK version):

```python
from claude_agent_sdk import AgentDefinition

agent1 = AgentDefinition(
    description="Normalizes all dates in a CSV to DD-MON-YYYY. Use for date cleanup.",
    prompt="...goal and criteria...",
    tools=["Read", "Write", "mcp__csvtools__parse_date"],
    model="sonnet",
)
```

Check the tools: confirm Agent 3 cannot call the CSV tools and no agent has Bash.

### Step 6. Coordinator with parallel invocation (key weak area)

Exam objectives: 1.2, 1.3 (parallel Task calls in one response), 1.6 (dynamic decomposition).

Prompt:

```
Create the coordinator in src/main.py. Requirements:
- ClaudeAgentOptions: agents dict with the three definitions; allowed_tools
  includes the subagent tool ("Task", called "Agent" in newer SDK versions;
  check the installed version), Read, Write, Glob, and the csvtools MCP tools
  only where needed.
- Python code (not the LLM) generates the run timestamp YYYYMMDD_HHMMSS in
  local time, creates work/<ts>/, and puts both in the coordinator prompt.
- Coordinator prompt states goals and quality criteria. It must first read
  and profile the CSV (date columns? calculated cells?). If there are no
  dates, skip agent1; if no calculated cells, skip agent2.
- When both are needed, invoke agent1 and agent2 in ONE response so they run
  in parallel. Paste the full CSV text, the schema and the rules into each
  subagent prompt; subagents do not inherit context.
- After both patch files exist, invoke agent3 with both patch contents
  included in its prompt.
- Time the parallel stage and log the elapsed seconds.
```

Run it on the sample file. In the logs, confirm both subagent calls appeared in the same assistant turn. Then temporarily force sequential execution and compare the timings; write both numbers in your notes.

Exam notes: subagents have isolated context; the coordinator controls all information flow.

### Step 7. Hooks: enforce the rules

Exam objectives: 1.4, 1.5.

Prompt:

```
Create src/hooks.py with:
1. PreToolUse hook (matcher "Write|Edit"): deny any write to app1.csv;
   allow writes inside work/<ts>/ only; deny writes to
   app1_updated_<ts>.csv unless manifest.json shows agent3 status "done".
2. PostToolUse hook (matcher "Write"): when a patch file is written inside
   work/<ts>/, mark that agent "done" in manifest.json.
Return a clear denial reason so the coordinator can react. Add tests that
call the hook functions directly.
```

Reference shape for a denial (confirm the format for your SDK version):

```python
async def guard(input_data, tool_use_id, context):
    path = input_data["tool_input"].get("file_path", "")
    if path.endswith("app1.csv"):
        return {"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "app1.csv is read-only"}}
    return {}
```

Test: ask the coordinator to write the final file early and watch the hook block it. This is the programmatic prerequisite pattern (compare sample question 1 in the exam guide).

### Step 8. Merge, validation, and the final write

Exam objectives: 4.4, 4.6, 5.3, 5.6.

Agent 3 (fresh context, no knowledge of how patches were produced) must:
- apply both patches to a copy of the data and write `work/<ts>/merged.csv`
- detect conflicts (two patches on one cell) and report them, never silently pick one
- write `merge_report.json` listing applied patches, conflicts, ambiguous dates, and unverifiable cells

Then the coordinator validates: same row and column count, no remaining non-standard dates, every Total and Avg consistent (use the calc_stats tool). If validation fails, it re-invokes the responsible agent once with the specific errors (retry with error feedback). If the information is simply not in the file, it does not retry and reports the gap instead.

Finally the coordinator writes `app1_updated_<ts>.csv` and `app1_changelog_<ts>.txt` into the project folder (allowed by the hook now that Agent 3 is done).

Prompt:

```
Update the coordinator prompt and add validation as described. If an agent
reports a structured error, proceed with partial results and mark the
affected cells as unverified in the change log. Distinguish an access
failure from a valid empty result.
```

### Step 9. State persistence and resume

Exam objectives: 1.7, 5.4 (manifest-based recovery).

The manifest at `work/<ts>/manifest.json` records each agent status and the patch file paths. Add a `--resume <timestamp>` option to `main.py`:

```
Add --resume <timestamp> to main.py. It loads the manifest, reuses the same
timestamp, tells the coordinator which agents are already done and where
their patch files are, and skips them. Add a test: kill the run after
agent1 finishes, resume, and verify agent1 is not run again.
```

Also practice the Claude Code side: name a session, leave, and come back with `claude --resume <name>`. Try forking a session to compare two prompt wordings for Agent 1.

### Step 10. Error propagation drills

Exam objectives: 2.2, 5.3.

Break things on purpose and read the logs:
1. Make `parse_date` raise a transient error once. Agent 1 should retry locally and only escalate what it cannot fix.
2. Put the value `TBD` in a date cell. Expect a structured validation error, a flag in the report, and the cell left unchanged.
3. Use a CSV with no dates. Expect Agent 1 skipped (valid empty result), not an error.
4. Stop Agent 2 mid-run. Expect partial results and a coverage note in the change log.

### Step 11. Claude Code workflow assets (skill, command, forked context)

Exam objectives: 3.2.

Prompt:

```
Create .claude/skills/date-format-check/SKILL.md with frontmatter:
context: fork, allowed-tools: Read, Grep, argument-hint: <csv path>.
It scans a CSV and lists every date format it finds, without modifying
anything. Also create .claude/commands/run-pipeline.md that runs the app
with a given timestamp option.
```

Run the skill on `app1.csv`. Confirm its output stays out of the main conversation context (forked). Write down the rule of thumb: CLAUDE.md for always-on rules, rules with globs for file-type conventions, skills for on-demand tasks, hooks for guaranteed enforcement, settings for permissions.

### Step 12. Test strategy (test first, then iterate)

Exam objectives: 3.5.

Write the test suite before fixing bugs:
- Unit tests: `parse_date` and `calc_stats` cases, hook decisions, filename pattern (`^app1_updated_\d{8}_\d{6}\.csv$`).
- End-to-end test: run on the sample file and compare to the expected table in section 2. Dates are deterministic, so assert exact values.
- Run the end-to-end test three times. LLM runs can vary, so record any flaky result and tighten the prompt with a concrete example.

When a test fails, paste the test output, the input, and the expected value to Claude Code.

### Step 13. Stretch exercises for remaining exam gaps

These are optional but target low-scoring areas.

**A. Large file and truncation (context optimization).** Generate a 500-row CSV. Make the coordinator split rows into chunks of 50, run Agent 2 per chunk, and merge the patches. Do not solve it by raising max_tokens. Trim tool outputs to the fields that matter.

**B. Raw API loop and tool_choice.** Write a standalone script using the Messages API: an agentic loop that continues while `stop_reason` is `tool_use` and stops on `end_turn`, appends tool results to the history, and uses a forced tool choice to guarantee the patch comes back as schema-valid JSON. Validate it with Pydantic and retry once with the validation error appended. Compare semantic errors (a wrong total that is valid JSON) with syntax errors.

**C. CI call.** Run `claude -p "Review src/ for bugs" --output-format json` in a script, and add `--json-schema` to get structured findings. Run it from a separate session than the one that wrote the code.

**D. MCP.** Move `parse_date` and `calc_stats` into a standalone MCP server configured in project `.mcp.json` with environment variable expansion. Expose the column catalog as an MCP resource.

**E. Batch decision.** Write two sentences on when the Message Batches API would suit this app (many files overnight) and when it would not (a user waiting for a result).

---

## 5. Exam objective map

| Step | Concepts practiced | Exam domain |
|---|---|---|
| 2 | CLAUDE.md hierarchy, rules with paths, settings | D3 |
| 3 | Plan mode vs direct execution, interview pattern | D3 |
| 4 | Tool descriptions, structured errors, isError | D2 |
| 5 | AgentDefinition, tool restriction, few-shot, goal-oriented prompts | D1, D2, D4 |
| 6 | Parallel subagents in one response, explicit context passing, dynamic decomposition | D1 |
| 7 | Hooks, programmatic prerequisites | D1 |
| 8 | Independent review, validation retry, provenance and conflicts | D4, D5 |
| 9 | Manifest, resume, fork | D1, D5 |
| 10 | Error propagation, valid empty vs failure | D2, D5 |
| 11 | Skills with context fork, commands | D3 |
| 12 | Test-driven iteration | D3 |
| 13 | Chunking, raw API loop, tool_choice, CI flags, MCP, batch | D1, D2, D3, D4, D5 |

## 6. Self-check questions

1. Why must the coordinator paste the CSV into each subagent prompt?
2. What evidence in the logs shows Agents 1 and 2 ran in parallel?
3. Why is a PreToolUse hook better than a prompt instruction for protecting `app1.csv`?
4. Why does Agent 3 get a fresh context instead of reusing a subagent that produced a patch?
5. When does a retry help, and when is it pointless?
6. Which configuration mechanism would you choose for: a naming convention that always applies, a convention for test files only, an on-demand analysis task, and a guaranteed block on a dangerous action?
7. What would change if the file had 50,000 rows?

## 7. Notes and cautions

- SDK names change between versions. The exam guide calls the subagent tool "Task"; newer SDK versions list it as "Agent". Check the installed version and its documentation, and ask Claude Code to confirm any field name before relying on it.
- The agents need an API key and incur usage cost. The small file keeps this low.
- Keep `work/` out of git. It holds run artifacts, not source.
- Never put the API key in CLAUDE.md, settings, or any file in the repo.
