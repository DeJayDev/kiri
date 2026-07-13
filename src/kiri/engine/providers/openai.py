import json
from typing import Any

from kiri import config, http
from kiri.engine.providers.base import Provider, ProviderError, normalize_usage


def to_messages(system, messages) -> list[dict[str, Any]]:
    # system arrives as ordered segments so a caching provider can place
    # breakpoints between them; here they just concatenate.
    text = system if isinstance(system, str) else "\n\n".join(s for s in system if s)
    out = [{"role": "system", "content": text}]
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


def to_tools(tools) -> list[dict[str, Any]] | None:
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


def to_content(message) -> list[dict[str, Any]]:
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
    return content


class OpenAI(Provider):
    name = "openai"

    def base_url(self):
        return (config.OPENAI_BASE_URL or "https://api.openai.com/v1").rstrip("/")

    def key(self):
        return config.OPENAI_API_KEY

    def missing(self):
        return None if self.key() else f"{self.name} api key"

    async def headers(self):
        return {"authorization": f"Bearer {self.key()}", "content-type": "application/json"}

    def output_tokens(self, usage):
        # OpenAI folds reasoning tokens into completion_tokens; xAI doesn't and
        # overrides this. Adding them here would double-count.
        return usage.get("completion_tokens", 0)

    def from_response(self, data) -> dict[str, Any]:
        choice = data["choices"][0]
        message = choice["message"]
        content = to_content(message)

        # From the content, not finish_reason: llama.cpp, vLLM and some Azure
        # deployments say "stop" while still returning tool_calls.
        stop = "tool_use" if any(b["type"] == "tool_use" for b in content) else "end_turn"

        usage = data.get("usage", {})
        # prompt_tokens includes the cached prefix; Anthropic's input_tokens excludes it.
        cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
        return {
            "content": content,
            "stop_reason": stop,
            "usage": normalize_usage(
                usage.get("prompt_tokens", 0) - cached,
                self.output_tokens(usage),
                cache_read=cached,
            ),
        }

    def check_model(self, requested, data):
        # No-op: OpenAI resolves an alias to a dated snapshot (gpt-4o ->
        # gpt-4o-2024-08-06), which is not a substitution. xAI overrides this.
        return

    async def complete(self, system, messages, tools, model=None):
        gap = self.missing()
        if gap:
            raise RuntimeError(f"{self.name}: not configured ({gap})")

        requested = model or config.MODEL
        body = {"model": requested, "messages": to_messages(system, messages)}
        converted = to_tools(tools)
        if converted:
            body["tools"] = converted

        url = f"{self.base_url()}/chat/completions"
        resp = await http.request("POST", url, headers=await self.headers(), json=body)
        if resp.status_code != 200:
            raise ProviderError(self.name, resp.status_code, resp.text)

        data = resp.json()
        self.check_model(requested, data)
        return self.from_response(data)
