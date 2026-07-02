import json
from typing import Any

import httpx

from kiri import config


def _endpoint():
    # OpenAI and any OpenAI-compatible endpoint via base_url. (OpenRouter does
    # not come here; it uses its native Anthropic endpoint in anthropic.py.)
    base = (config.OPENAI_BASE_URL or "https://api.openai.com/v1").rstrip("/")
    return f"{base}/chat/completions", config.OPENAI_API_KEY


def _to_messages(system, messages) -> list[dict[str, Any]]:
    out = [{"role": "system", "content": system}]
    for m in messages:
        content = m["content"]
        if isinstance(content, str):
            out.append({"role": m["role"], "content": content})
            continue
        if m["role"] == "assistant":
            text = ""
            calls = []
            for block in content:
                if block["type"] == "text":
                    text += block["text"]
                elif block["type"] == "tool_use":
                    calls.append(
                        {
                            "id": block["id"],
                            "type": "function",
                            "function": {
                                "name": block["name"],
                                "arguments": json.dumps(block.get("input", {})),
                            },
                        }
                    )
            msg = {"role": "assistant", "content": text or None}
            if calls:
                msg["tool_calls"] = calls
            out.append(msg)
            continue
        for block in content:  # user turn carrying tool_result blocks
            if block.get("type") == "tool_result":
                out.append(
                    {
                        "role": "tool",
                        "tool_call_id": block["tool_use_id"],
                        "content": block.get("content", ""),
                    }
                )
    return out


def _to_tools(tools) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t["input_schema"],
            },
        }
        for t in tools
    ]


def _from_response(data):
    choice = data["choices"][0]
    message = choice["message"]
    content = []
    if message.get("content"):
        content.append({"type": "text", "text": message["content"]})
    for call in message.get("tool_calls") or []:
        try:
            parsed = json.loads(call["function"].get("arguments") or "{}")
        except json.JSONDecodeError:
            parsed = {}
        content.append(
            {
                "type": "tool_use",
                "id": call["id"],
                "name": call["function"]["name"],
                "input": parsed,
            }
        )
    stop = "tool_use" if choice.get("finish_reason") == "tool_calls" else "end_turn"
    usage = data.get("usage", {})
    return {
        "content": content,
        "stop_reason": stop,
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        },
    }


async def complete(system, messages, tools):
    url, key = _endpoint()
    if not key:
        raise RuntimeError(f"{config.PROVIDER}: api key not set")

    body = {
        "model": config.MODEL,
        "messages": _to_messages(system, messages),
    }
    converted = _to_tools(tools)
    if converted:
        body["tools"] = converted

    headers = {"authorization": f"Bearer {key}", "content-type": "application/json"}

    async with httpx.AsyncClient(timeout=httpx.Timeout(600.0)) as client:
        resp = await client.post(url, headers=headers, json=body)

    if resp.status_code != 200:
        raise RuntimeError(f"{config.PROVIDER} {resp.status_code}: {resp.text}")
    return _from_response(resp.json())
