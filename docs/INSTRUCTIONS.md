# Project 1: How to set up, run and change this pipeline

This app cleans up `app1.csv` using a coordinator and three AI subagents:

| Agent | Job |
|---|---|
| Agent 1 | Converts every date to `DD-MON-YYYY` (e.g. `04-MAR-2026`) |
| Agent 2 | Checks every `Total` / `Avg` / `TOTAL` cell and fixes wrong values |
| Agent 3 | Merges the changes from Agents 1 and 2 |

The coordinator starts Agents 1 and 2 at the same time, then Agent 3. The original
`app1.csv` is never modified. Results are written next to it as
`app1_updated_<YYYYMMDD_HHMMSS>.csv` plus `app1_changelog_<YYYYMMDD_HHMMSS>.txt`.

Rules for the project are in `CLAUDE.md` (one folder up). The step-by-step design is in
`TUTORIAL.md` (same folder).

---

## 1. Prerequisites

Install these once (macOS, using Homebrew):

```bash
brew install python@3.13 git gh
```

- **Python 3.10 or newer.** The project is tested on 3.13.
- **git** to track changes, and **gh** (GitHub CLI) to open pull requests.
- **An Anthropic API key.** The pipeline calls the Claude API, so it needs one.
  See section 3.

Check what you have:

```bash
python3.13 --version
git --version
gh --version
```

## 2. Get the code

```bash
mkdir -p ~/Training/CCAF
cd ~/Training/CCAF
git clone https://github.com/srinivaskadiyala/CCAR-F-Project-1.git project1
cd project1
```

If you already have the folder, skip this and just `cd ~/Training/CCAF/project1`.

## 3. Create the virtual environment

The virtual environment (venv) keeps this project's Python packages separate from
everything else. By project convention it lives at `~/Training/.venv`, **outside**
the project folder.

```bash
cd ~/Training
python3.13 -m venv .venv
source .venv/bin/activate
pip install claude-agent-sdk pytest pydantic
```

Check that it worked:

```bash
python -c "import claude_agent_sdk; print('SDK OK')"
```

Notes:

- **Always create the venv with an explicit version (`python3.13`).** Plain
  `python3` on a Mac may be the old system Python 3.9, which is too old and does
  not work with the SDK. If `python -c "import claude_agent_sdk"` fails with
  `ModuleNotFoundError` even after installing, your venv's `python` is probably the
  wrong version. Check with `python --version`, or call the right one directly:
  `~/Training/.venv/bin/python3.13`.
- You must activate the venv in every new terminal:
  `source ~/Training/.venv/bin/activate`. Your prompt then starts with `(.venv)`.
- Leave the venv with `deactivate`.

## 4. Set up the API key

Never put the key in the repo, in `CLAUDE.md`, or in any file that gets committed.
The convention here is a private file outside the project: `~/Training/.env.sh`.

Create it (replace the placeholder with your real key):

```bash
cat > ~/Training/.env.sh <<'EOF'
export ANTHROPIC_API_KEY="sk-ant-your-key-here"
EOF
chmod 600 ~/Training/.env.sh
```

`chmod 600` makes the file readable only by you.

Load the key into your current terminal before each session:

```bash
source ~/Training/.env.sh
```

Check without printing the key:

```bash
echo "key set: ${ANTHROPIC_API_KEY:+yes}"
```

It should print `key set: yes`. The key only lasts for that terminal window. If you
want it loaded automatically, add `source ~/Training/.env.sh` to `~/.zshrc`.

## 5. Run the pipeline

Each run costs real money and takes a few minutes. On the current 25-line `app1.csv`,
three measured runs took 2.5 to 3 minutes and cost $0.57 to $0.79 each. (The old 6-row
sample cost roughly $0.35 to $0.50 and took 90 to 100 seconds.) Cost grows with file
size. One of those three runs needed the built-in retry (the first merge failed
verification and was fixed on the second pass), so expect an occasional longer, dearer run.

```bash
cd ~/Training/CCAF/project1
source ~/Training/.venv/bin/activate
source ~/Training/.env.sh
python src/main.py
```

What you should see:

```
[coordinator] launched ['agent1_dates', 'agent2_math'] in one response
[coordinator] launched ['agent3_merge'] in one response
{ "final": "app1_updated_<timestamp>.csv", "changelog": "app1_changelog_<timestamp>.txt", ... }
```

The first line proves Agents 1 and 2 were started together (in parallel).

Results:

| File | What it is |
|---|---|
| `app1_updated_<ts>.csv` | The cleaned data |
| `app1_changelog_<ts>.txt` | Every change made, ambiguous dates, conflicts, unverified cells |
| `work/<ts>/` | Working files: each agent's patch, `merged.csv`, `merge_report.json`, `manifest.json` |

All three use the same timestamp, which is created once at the start of the run.
These output files and `work/` are ignored by git on purpose.

**Optional: run Agents 1 and 2 one after the other** to compare timing:

```bash
python src/main.py --sequential
```

The log line `stage_seconds` shows how long Agents 1 and 2 took (about 9 s in parallel
vs about 39 s sequentially, measured on the old 6-row sample).

**If it fails:** the program prints which checks failed. It tries to fix the problem
once, and if it still fails it writes no final files and exits with an error.
Look inside `work/<ts>/` to see what each agent produced.

## 6. Run the tests

There are two kinds of test.

### Without the real model (free, fast, run these often)

```bash
cd ~/Training/CCAF/project1
source ~/Training/.venv/bin/activate
pytest
```

This runs the 53 unit tests in about a second. They check date parsing, the sum and
average maths, the write-protection hooks, the validation logic and file naming. No
API key is needed and nothing is billed. The two end-to-end tests are skipped by
default (the output says `2 deselected`).

Useful variations:

```bash
pytest -v                        # list each test
pytest tests/test_tools.py       # one file only
pytest -k "date"                 # only tests with "date" in the name
```

### With the real model (end to end; costs money)

This runs the whole pipeline on `app1.csv` and compares **every cell** of the output
with `tests/fixtures/expected_app1.csv` (the correct answer: 23 normalised dates,
corrected Totals and Avgs, corrected TOTAL row). It also checks that Agents 1 and 2
were launched together and that `app1.csv` is unchanged. It cleans up the files it
creates.

```bash
source ~/Training/.env.sh
pytest -m slow tests/test_e2e.py
```

Takes roughly 3 minutes and costs real money (about $0.60 to $0.80). If `ANTHROPIC_API_KEY` is not
set, these tests skip themselves instead of failing.

LLM output can vary from run to run. If an end-to-end test fails once, run it again
before assuming there is a bug, and tell the team if it fails repeatedly.

## 7. Making changes and checking them in to GitHub

The repo is https://github.com/srinivaskadiyala/CCAR-F-Project-1. `main` is the
stable branch. Do not commit straight to it; use a branch and a pull request (PR).

### One-time: sign in to GitHub

```bash
gh auth login
```

Choose GitHub.com, HTTPS, and log in through the browser. Check with `gh auth status`.

### For every change

```bash
cd ~/Training/CCAF/project1
git checkout main
git pull                                   # get the latest code
git checkout -b my-change-name             # new branch for your work

# ... edit files, then run the tests ...
pytest

git status                                 # see what changed
git diff                                   # read your changes
git add path/to/changed_file.py            # stage specific files
git commit -m "Short description of the change"

git push -u origin my-change-name          # first push of this branch
gh pr create --base main --fill            # open the pull request
```

After the PR is reviewed:

```bash
gh pr merge --merge                        # or merge it on the GitHub website
git checkout main
git pull
git branch -d my-change-name               # delete the local branch
```

Tips:

- Add specific files by name rather than `git add .`, so you do not commit something by
  accident. Never commit `.env`, API keys, or generated files.
- Keep each commit small and focused, with a message saying what and why.
- Run `pytest` before every commit.
- Made a mistake before committing? `git restore path/to/file` discards your edits to
  that file (this cannot be undone), and `git restore --staged path/to/file` unstages it.
- Use `git log --oneline` to see history.

## 8. Project layout

```
project1/
├── CLAUDE.md               rules and requirements (R1 to R8) for Claude Code
├── app1.csv                the input data: 25 lines with seeded errors (protected)
├── pytest.ini              test settings (slow tests are off by default)
├── .claude/
│   ├── settings.json       permissions (app1.csv is write-protected)
│   └── rules/              CSV conventions, loaded only when working on CSV/test files
├── docs/
│   ├── INSTRUCTIONS.md     this file
│   └── TUTORIAL.md         the design and the build steps
├── src/
│   ├── main.py             entry point: runs everything, verifies, writes final files
│   ├── agents.py           the three agent definitions and the coordinator prompt
│   ├── tools.py            parse_date and calc_stats (the exact-answer tools)
│   ├── hooks.py            guard rules that block forbidden file writes
│   ├── schemas.py          data formats for patches, merge report, manifest
│   └── validate.py         checks run on Agent 3's output before the final write
├── tests/                  unit tests plus the end-to-end test
│   └── fixtures/           sample6.csv (old 6-row sample), expected_app1.csv (correct answer)
└── work/<timestamp>/       created per run (not in git)
```

## 9. Using Claude Code on this project

Start it from the project folder so it picks up `CLAUDE.md`, the rules and the
permissions:

```bash
cd ~/Training/CCAF/project1
source ~/Training/.venv/bin/activate
source ~/Training/.env.sh
claude
```

Inside Claude Code, `/memory` shows which `CLAUDE.md` files are loaded. Press
Shift+Tab to switch to plan mode before larger changes.

## 10. Troubleshooting

| Problem | Likely cause and fix |
|---|---|
| `ModuleNotFoundError: claude_agent_sdk` | The venv is not active, or its `python` is the old 3.9. Run `source ~/Training/.venv/bin/activate` and check `python --version` is 3.10 or newer. Otherwise recreate the venv with `python3.13 -m venv`. |
| `key set:` prints nothing | You have not run `source ~/Training/.env.sh` in this terminal, or the file is missing or has no `export ANTHROPIC_API_KEY=...` line. |
| Authentication or 401 errors | The key is wrong, expired or out of credit. Check it in the Anthropic console. |
| `pytest` says `2 deselected` | Normal. Those are the paid end-to-end tests. Use `pytest -m slow` to include them. |
| `pytest: command not found` | Activate the venv. |
| A write was denied (hook message) | By design. `app1.csv` cannot be modified, and final files cannot be written before Agent 3 finishes. |
| Run says `still failing; no final files written` | The merged output failed verification twice. Read the listed problems and inspect `work/<ts>/`. |
| `git push` is rejected | Run `git pull` first, or you are on a branch that is not yours. Do not force-push to `main`. |
| `gh: command not found` | `brew install gh`, then `gh auth login`. |

## 11. Safety reminders

- Never commit the API key. It belongs only in `~/Training/.env.sh`.
- `app1.csv` must stay unchanged by the pipeline and by Claude Code (a deny rule in
  `.claude/settings.json` blocks edits). To test with different data, add a fixture under
  `tests/fixtures/`. If you deliberately change `app1.csv` yourself, also update
  `tests/fixtures/expected_app1.csv` (the correct result) and the counts asserted in
  `tests/test_validate.py`, then run `pytest` and `pytest -m slow tests/test_e2e.py`.

## 12. Keeping this file up to date

Treat `INSTRUCTIONS.md` like code. In the same PR as any change that affects setup,
commands, test counts, costs, file layout or behaviour described here, update this file.
A PR that changes those without updating it is incomplete.
- Every pipeline run and every `-m slow` test uses paid API calls. Run `pytest` (no flags)
  while developing and the paid runs only when you need them.
