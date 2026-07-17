import asyncio
import time

from kiri import config
from kiri.scheduling import tool as scheduler
from kiri.tools import registry as tools
from kiri.tools import shell, web


def test_registry_unknown_tool_returns_error():
    registry = tools.build(store=None, channel_id=1, mcp_tools=[], transport=None)
    assert "unknown tool" in asyncio.run(registry.run("nope", {}))


def test_registry_merges_mcp_tools():
    async def runner(args):
        return "mcp-ok"

    schema = {"name": "srv__t", "description": "", "input_schema": {"type": "object"}}
    registry = tools.build(store=None, channel_id=1, mcp_tools=[(schema, runner)], transport=None)
    assert "srv__t" in {s["name"] for s in registry.schemas()}
    assert asyncio.run(registry.run("srv__t", {})) == "mcp-ok"


def test_shell_caps_output(monkeypatch):
    monkeypatch.setattr(config, "SHELL_OUTPUT_CAP", 10)
    assert "[truncated]" in shell._cap("x" * 50)


def test_web_search_without_key(monkeypatch):
    monkeypatch.setattr(config, "EXA_API_KEY", None)
    out = asyncio.run(web.search({"query": "hi"}))
    assert "EXA_API_KEY not set" in out


def test_schedule_tool_rejects_bad_cron():
    runners = {schema["name"]: run for schema, run in scheduler.build(store=None, channel_id=1)}
    out = asyncio.run(runners["schedule_job"]({"cron": "not a cron", "instruction": "x"}))
    assert "invalid cron" in out


class _FakeStore:
    def __init__(self):
        self.added = []

    def add_once(self, when, instruction, channel_id):
        self.added.append((when, instruction, channel_id))
        return 7


def _remind_runner(store):
    return {schema["name"]: run for schema, run in scheduler.build(store, channel_id=1)}["remind"]


def test_remind_rejects_past_time():
    out = asyncio.run(_remind_runner(_FakeStore())({"when": "2000-01-01T00:00:00Z", "instruction": "x"}))
    assert "past" in out


def test_remind_schedules_future():
    store = _FakeStore()
    out = asyncio.run(_remind_runner(store)({"when": "2999-01-01T00:00:00Z", "instruction": "ping"}))
    assert "reminder 7" in out
    assert store.added[0][1] == "ping"


def test_parse_when_iso_and_epoch():
    assert scheduler._parse_when("2999-01-01T00:00:00Z") is not None
    assert scheduler._parse_when("1700000000") == 1700000000.0
    assert scheduler._parse_when("garbage") is None


def test_shell_times_out_and_tells_the_agent_how_to_retry():
    out = asyncio.run(shell.run({"command": "sleep 30", "timeout": 1}))
    assert "killed after 1s" in out
    assert "`timeout`" in out


def test_shell_runs_to_completion_within_its_timeout():
    out = asyncio.run(shell.run({"command": "sleep 0.5 && printf done", "timeout": 10}))
    assert "exit: 0" in out
    assert "done" in out


def test_shell_timeout_kills_the_whole_process_tree(tmp_path):
    # The shell exits but a child keeps the pipes open; killing only the shell
    # would hang the drain. Marker file proves the child died too.
    marker = tmp_path / "marker"
    command = f"(sleep 2; touch {marker}) & wait"
    asyncio.run(shell.run({"command": command, "timeout": 1}))
    time.sleep(2)
    assert not marker.exists()
