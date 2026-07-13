import asyncio
import json

import pytest

from kiri import config
from kiri.engine import providers
from kiri.engine.providers import anthropic, openai, xai
from kiri.engine.providers.base import ProviderError

_INTERNAL = [
    {"role": "user", "content": "run ls"},
    {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "sure"},
            {"type": "tool_use", "id": "call_1", "name": "shell", "input": {"command": "ls"}},
        ],
    },
    {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "call_1", "content": "file.txt"}],
    },
]


def test_unknown_provider_is_fatal():
    try:
        providers.build("nope")
    except SystemExit as exc:
        assert "Unknown provider" in str(exc)
    else:
        raise AssertionError("expected SystemExit")


def test_cache_breakpoint_on_last_system_block():
    blocks = anthropic._system_blocks(["BASE", "SUMMARY"])
    assert [b["text"] for b in blocks] == ["BASE", "SUMMARY"]
    assert "cache_control" not in blocks[0]
    assert blocks[-1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


def test_cache_breakpoint_on_last_message_block():
    messages = [
        {"role": "user", "content": "hi"},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "a", "content": "ok"}]},
    ]
    out = anthropic._messages(messages)
    assert out[-1]["content"][-1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


def test_cache_marking_never_mutates_the_session_history():
    messages = [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]
    anthropic._messages(messages)
    assert messages == [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]


def test_to_messages_roundtrip():
    out = openai.to_messages("SYS", _INTERNAL)
    assert [m["role"] for m in out] == ["system", "user", "assistant", "tool"]
    assert out[0]["content"] == "SYS"
    call = out[2]["tool_calls"][0]
    assert call["function"]["name"] == "shell"
    assert json.loads(call["function"]["arguments"]) == {"command": "ls"}
    assert out[3]["tool_call_id"] == "call_1"


def test_to_messages_joins_system_segments():
    out = openai.to_messages(["BASE", "", "SUMMARY"], [])
    assert out[0]["content"] == "BASE\n\nSUMMARY"


def test_to_messages_tool_only_assistant_has_null_content():
    msgs = [{"role": "assistant", "content": [{"type": "tool_use", "id": "a", "name": "x", "input": {}}]}]
    out = openai.to_messages("S", msgs)
    assert out[1]["content"] is None
    assert "tool_calls" in out[1]


def _tool_call_response(finish_reason):
    return {
        "model": "gpt-4o",
        "choices": [
            {
                "finish_reason": finish_reason,
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "c1",
                            "function": {"name": "shell", "arguments": '{"command": "ls"}'},
                        }
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2},
    }


def test_openai_stop_reason_derived_from_content_not_finish_reason():
    for finish_reason in ("tool_calls", "stop"):
        out = openai.OpenAI().from_response(_tool_call_response(finish_reason))
        assert out["stop_reason"] == "tool_use"
        assert out["content"][0]["input"] == {"command": "ls"}


def test_openai_bad_json_args_fall_back_to_empty():
    data = {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": "hello",
                    "tool_calls": [{"id": "c", "function": {"name": "f", "arguments": "{bad"}}],
                },
            }
        ],
        "usage": {},
    }
    out = openai.OpenAI().from_response(data)
    assert out["stop_reason"] == "tool_use"
    assert next(b for b in out["content"] if b["type"] == "tool_use")["input"] == {}


def test_openai_splits_cached_tokens_out_of_input():
    data = {
        "choices": [{"finish_reason": "stop", "message": {"content": "hi"}}],
        "usage": {
            "prompt_tokens": 1000,
            "completion_tokens": 20,
            "prompt_tokens_details": {"cached_tokens": 900},
        },
    }
    usage = openai.OpenAI().from_response(data)["usage"]
    assert usage["input_tokens"] == 100
    assert usage["cache_read_input_tokens"] == 900
    assert usage["output_tokens"] == 20


def test_openai_does_not_flag_a_dated_snapshot_as_substitution():
    openai.OpenAI().check_model("gpt-4o", {"model": "gpt-4o-2024-08-06"})


def test_xai_adds_reasoning_tokens_to_output():
    # xAI excludes reasoning tokens from completion_tokens; OpenAI includes them.
    # Getting this wrong reports a 36-token reply as 1 token.
    usage = {"completion_tokens": 1, "completion_tokens_details": {"reasoning_tokens": 35}}
    assert xai.XAI().output_tokens(usage) == 36
    # ...and the base provider must NOT do this, or OpenAI double-counts.
    assert openai.OpenAI().output_tokens(usage) == 1


def test_xai_rejects_a_substituted_model():
    try:
        xai.XAI().check_model("grok-4", {"model": "grok-4.3"})
    except RuntimeError as exc:
        assert "grok-4.3" in str(exc)
    else:
        raise AssertionError("expected a substituted model to raise")


def _xai_raising(monkeypatch, error):
    provider = xai.XAI()

    async def boom(*args, **kwargs):
        raise error

    monkeypatch.setattr(openai.OpenAI, "complete", boom)
    monkeypatch.setattr(config, "XAI_API_KEY", None)
    return provider


def test_xai_explains_a_real_403(monkeypatch):
    provider = _xai_raising(monkeypatch, ProviderError("xai", 403, "forbidden"))
    with pytest.raises(RuntimeError, match="allowlists OAuth API access"):
        asyncio.run(provider.complete([], [], None))


def test_xai_does_not_cry_403_at_a_500_whose_body_mentions_403(monkeypatch):
    body = '{"error": "internal", "docs": "https://x.ai/errors#403"}'
    provider = _xai_raising(monkeypatch, ProviderError("xai", 500, body))
    with pytest.raises(ProviderError) as exc:
        asyncio.run(provider.complete([], [], None))
    assert exc.value.status == 500
    assert "allowlists" not in str(exc.value)


def test_xai_needs_a_client_id_until_it_has_a_credential(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CREDENTIALS_PATH", str(tmp_path / "c.json"))
    monkeypatch.setattr(config, "XAI_API_KEY", None)
    monkeypatch.setattr(config, "XAI_CLIENT_ID", None)
    assert "client_id" in xai.XAI().missing()

    monkeypatch.setattr(config, "XAI_CLIENT_ID", "cid")
    assert xai.XAI().missing() is None
