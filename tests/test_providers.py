import asyncio
import json

import pytest

from kiri import config, http
from kiri.engine.providers import anthropic, openai, xai
from kiri.engine.providers import registry as providers
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
        assert "unknown provider" in str(exc)
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


def test_to_messages_translates_an_image_user_turn():
    msgs = [
        {
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "QUJD"}},
                {"type": "text", "text": "what is this"},
            ],
        }
    ]
    out = openai.to_messages("S", msgs)
    assert [p["type"] for p in out[1]["content"]] == ["image_url", "text"]
    assert out[1]["content"][0]["image_url"]["url"] == "data:image/png;base64,QUJD"


def test_anthropic_leaves_image_blocks_untouched():
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "QUJD"}},
                {"type": "text", "text": "hi"},
            ],
        }
    ]
    out = anthropic._messages(messages)
    assert out[-1]["content"][0] == messages[0]["content"][0]
    assert out[-1]["content"][-1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


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


def test_openai_strips_a_leaked_control_token_from_text():
    data = {
        "choices": [{"finish_reason": "stop", "message": {"content": "here you go<|eof|>"}}],
        "usage": {},
    }
    out = openai.OpenAI().from_response(data)
    assert out["content"] == [{"type": "text", "text": "here you go"}]


def test_openai_drops_a_reply_that_is_only_a_control_token():
    data = {
        "choices": [{"finish_reason": "stop", "message": {"content": "<|eof|>"}}],
        "usage": {},
    }
    out = openai.OpenAI().from_response(data)
    assert out["content"] == []
    assert out["stop_reason"] == "end_turn"


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
    with pytest.raises(RuntimeError, match="allowlisted separately from the subscription"):
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


class _StreamResponse:
    def __init__(self, lines, status=200):
        self.lines = lines
        self.status_code = status
        self.text = "boom"
        self.closed = False

    async def aiter_lines(self):
        for line in self.lines:
            yield line

    async def aread(self):
        return b"boom"

    async def aclose(self):
        self.closed = True


def _serve(monkeypatch, response):
    sent = {}

    async def request(method, url, headers=None, json=None, stream=False, **kwargs):
        sent.update(json=json, stream=stream)
        return response

    monkeypatch.setattr(http, "request", request)
    return sent


def _sse(*events):
    return [f"data: {json.dumps(event)}" for event in events]


def test_anthropic_stream_rebuilds_text_and_tool_use_and_feeds_text(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "k")
    response = _StreamResponse(_sse(
        {"type": "message_start", "message": {"content": [], "stop_reason": None, "usage": {"input_tokens": 10, "cache_read_input_tokens": 90, "output_tokens": 1}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "look"}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "ing"}},
        {"type": "content_block_stop", "index": 0},
        {"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "t1", "name": "shell", "input": {}}},
        {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": '{"command": '}},
        {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": '"ls"}'}},
        {"type": "content_block_stop", "index": 1},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 20}},
        {"type": "message_stop"},
    ))
    sent = _serve(monkeypatch, response)
    fed = []

    data = asyncio.run(anthropic.Anthropic().complete("SYS", [{"role": "user", "content": "hi"}], None, on_text=fed.append))

    assert sent["stream"] and sent["json"]["stream"]
    assert fed == ["look", "ing"]
    assert data["content"] == [
        {"type": "text", "text": "looking"},
        {"type": "tool_use", "id": "t1", "name": "shell", "input": {"command": "ls"}},
    ]
    assert data["stop_reason"] == "tool_use"
    assert data["usage"]["input_tokens"] == 10
    assert data["usage"]["cache_read_input_tokens"] == 90
    assert data["usage"]["output_tokens"] == 20
    assert response.closed


def test_anthropic_stream_error_event_raises(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "k")
    response = _StreamResponse(_sse(
        {"type": "message_start", "message": {"content": [], "usage": {}}},
        {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}},
    ))
    _serve(monkeypatch, response)

    with pytest.raises(ProviderError) as caught:
        asyncio.run(anthropic.Anthropic().complete("SYS", [{"role": "user", "content": "hi"}], None, on_text=lambda d: None))
    assert "overloaded_error" in str(caught.value)
    assert response.closed


def test_anthropic_stream_http_error_carries_the_status(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "k")
    _serve(monkeypatch, _StreamResponse([], status=400))

    with pytest.raises(ProviderError) as caught:
        asyncio.run(anthropic.Anthropic().complete("SYS", [{"role": "user", "content": "hi"}], None, on_text=lambda d: None))
    assert caught.value.status == 400


def test_openai_stream_rebuilds_text_tool_calls_and_usage(monkeypatch):
    monkeypatch.setattr(config, "OPENAI_API_KEY", "k")
    monkeypatch.setattr(config, "MODEL", "gpt-x")
    response = _StreamResponse(_sse(
        {"model": "gpt-x", "choices": [{"delta": {"content": "on "}}]},
        {"model": "gpt-x", "choices": [{"delta": {"content": "it"}}]},
        {"model": "gpt-x", "choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "shell", "arguments": '{"comm'}}]}}]},
        {"model": "gpt-x", "choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": 'and": "ls"}'}}]}}]},
        {"model": "gpt-x", "choices": [], "usage": {"prompt_tokens": 100, "completion_tokens": 7, "prompt_tokens_details": {"cached_tokens": 60}}},
    ) + ["data: [DONE]"])
    sent = _serve(monkeypatch, response)
    fed = []

    data = asyncio.run(openai.OpenAI().complete("SYS", [{"role": "user", "content": "hi"}], None, on_text=fed.append))

    assert sent["json"]["stream_options"] == {"include_usage": True}
    assert fed == ["on ", "it"]
    assert data["content"] == [
        {"type": "text", "text": "on it"},
        {"type": "tool_use", "id": "c1", "name": "shell", "input": {"command": "ls"}},
    ]
    assert data["stop_reason"] == "tool_use"
    assert data["usage"]["input_tokens"] == 40
    assert data["usage"]["cache_read_input_tokens"] == 60


def test_xai_stream_does_not_ask_for_usage_it_reports_unasked(monkeypatch):
    monkeypatch.setattr(config, "XAI_API_KEY", "k")
    monkeypatch.setattr(config, "MODEL", "grok-x")
    response = _StreamResponse(_sse(
        {"model": "grok-x", "choices": [{"delta": {"content": "hi"}}], "usage": {"prompt_tokens": 5, "completion_tokens": 1}},
    ) + ["data: [DONE]"])
    sent = _serve(monkeypatch, response)

    asyncio.run(xai.XAI().complete("SYS", [{"role": "user", "content": "hi"}], None, on_text=lambda d: None))
    assert "stream_options" not in sent["json"]
