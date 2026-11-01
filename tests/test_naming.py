import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agents import AGENTS  # noqa: E402
from main import make_timestamp, task_prompt  # noqa: E402

FINAL = re.compile(r"^app1_updated_\d{8}_\d{6}\.csv$")


def test_timestamp_format_and_filename() -> None:
    ts = make_timestamp()
    assert re.fullmatch(r"\d{8}_\d{6}", ts)
    assert FINAL.match(f"app1_updated_{ts}.csv")
    assert not FINAL.match("app1_updated_2026.csv")


def test_task_prompt_reuses_one_timestamp() -> None:
    p = task_prompt("20261031_120000")
    assert p.count("20261031_120000") >= 4


def test_agent_tool_restrictions() -> None:
    assert AGENTS["agent3_merge"].tools == ["Read", "Write"]
    for a in AGENTS.values():
        assert "Bash" not in a.tools
    assert "mcp__csvtools__parse_date" not in AGENTS["agent2_math"].tools
    assert "mcp__csvtools__calc_stats" not in AGENTS["agent1_dates"].tools
