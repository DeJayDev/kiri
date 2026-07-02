import json

from kiri import config
from kiri.engine.providers import anthropic, openai


def test_anthropic_endpoint_default(monkeypatch):
    monkeypatch.setattr(config, "PROVIDER", "anthropic")
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "k")
    url, headers, key = anthropic._endpoint()
    assert url.endswith("api.anthropic.com/v1/messages")
    assert headers["x-api-key"] == "k"
    assert headers["anthropic-version"]
    assert key == "k"


def test_openrouter_uses_native_anthropic_endpoint(monkeypatch):
    monkeypatch.setattr(config, "PROVIDER", "openrouter")
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "or")
    url, headers, key = anthropic._endpoint()
    assert "openrouter.ai/api/v1/messages" in url
    assert headers["authorization"] == "Bearer or"
    assert "x-api-key" not in headers
    assert key == "or"


def test_openai_endpoint_default(monkeypatch):
    monkeypatch.setattr(config, "OPENAI_BASE_URL", None)
    monkeypatch.setattr(config, "OPENAI_API_KEY", "oa")
    url, key = openai._endpoint()
    assert url == "https://api.openai.com/v1/chat/completions"
    assert key == "oa"


def test_openai_base_url_override(monkeypatch):
    monkeypatch.setattr(config, "OPENAI_BASE_URL", "http://local:1234/v1/")
    monkeypatch.setattr(config, "OPENAI_API_KEY", "x")
    url, _ = openai._endpoint()
    assert url == "http://local:1234/v1/chat/completions"


_INTERNAL = [
    {"role": "user", "content": "run ls"},
    {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "sure"},
            {"type": "tool_use", "id": "call_1", "name": "shell", "input": {"command": "ls"}},
        ],
    },
    {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call_1", "content": "file.txt"}]},
]


def test_to_messages_roundtrip():
    out = openai._to_messages("SYS", _INTERNAL)
    assert [m["role"] for m in out] == ["system", "user", "assistant", "tool"]
    assert out[0]["content"] == "SYS"
    assistant = out[2]
    assert assistant["content"] == "sure"
    call = assistant["tool_calls"][0]
    assert call["function"]["name"] == "shell"
    assert json.loads(call["function"]["arguments"]) == {"command": "ls"}
    assert out[3]["tool_call_id"] == "call_1"
    assert out[3]["content"] == "file.txt"


def test_to_messages_tool_only_assistant_has_null_content():
    msgs = [{"role": "assistant", "content": [{"type": "tool_use", "id": "a", "name": "x", "input": {}}]}]
    out = openai._to_messages("S", msgs)
    assert out[1]["content"] is None
    assert "tool_calls" in out[1]


def test_to_tools_shape_and_none():
    out = openai._to_tools([{"name": "shell", "description": "d", "input_schema": {"type": "object"}}])
    assert out is not None
    assert out[0]["type"] == "function"
    assert out[0]["function"]["name"] == "shell"
    assert out[0]["function"]["parameters"] == {"type": "object"}
    assert openai._to_tools(None) is None
    assert openai._to_tools([]) is None


def test_from_response_tool_use():
    resp = {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "content": "ok",
                    "tool_calls": [
                        {"id": "call_9", "function": {"name": "web_search", "arguments": '{"query":"hi"}'}}
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2},
    }
    canon = openai._from_response(resp)
    assert canon["stop_reason"] == "tool_use"
    assert [b["type"] for b in canon["content"]] == ["text", "tool_use"]
    assert canon["content"][1]["input"] == {"query": "hi"}
    assert canon["usage"] == {"input_tokens": 10, "output_tokens": 2}


def test_from_response_end_turn_and_bad_json_args():
    resp = {
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
    canon = openai._from_response(resp)
    assert canon["stop_reason"] == "end_turn"
    tool_use = next(b for b in canon["content"] if b["type"] == "tool_use")
    assert tool_use["input"] == {}
    assert canon["usage"] == {"input_tokens": 0, "output_tokens": 0}
