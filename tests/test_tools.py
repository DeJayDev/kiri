import asyncio

from kiri import config, tools
from kiri.engine import prompt
from kiri.scheduling import tool as scheduler
from kiri.tools import shell, web


def test_registry_has_core_tools():
    registry = tools.build(store=None, channel_id=1, mcp_tools=[])
    names = {s["name"] for s in registry.schemas()}
    assert {"shell", "web_search", "web_fetch", "schedule_job", "list_jobs", "cancel_job"} <= names


def test_registry_unknown_tool_returns_error():
    registry = tools.build(store=None, channel_id=1, mcp_tools=[])
    assert "unknown tool" in asyncio.run(registry.run("nope", {}))


def test_registry_merges_mcp_tools():
    async def runner(args):
        return "mcp-ok"

    schema = {"name": "srv__t", "description": "", "input_schema": {"type": "object"}}
    registry = tools.build(store=None, channel_id=1, mcp_tools=[(schema, runner)])
    assert "srv__t" in {s["name"] for s in registry.schemas()}
    assert asyncio.run(registry.run("srv__t", {})) == "mcp-ok"


def test_shell_runs_command():
    out = asyncio.run(shell.run({"command": "printf hi"}))
    assert "exit: 0" in out
    assert "hi" in out


def test_shell_rejects_empty():
    assert "empty" in asyncio.run(shell.run({"command": "   "}))


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


def test_default_prompt_loads():
    assert "Kiri" in prompt.load()
