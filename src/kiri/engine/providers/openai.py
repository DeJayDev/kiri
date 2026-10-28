import json
import re
from typing import Any

from kiri import config, http
from kiri.engine.providers.base import Provider, ProviderError, normalize_usage

# Some OpenAI-compatible endpoints leak the model's end-of-turn control token
# (e.g. <|eof|>, <|endoftext|>) into message content instead of stopping on it.
_CONTROL = re.compile(r"<\|[^|>]*\|>")


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
        # A user turn carries tool_results (each its own tool message) and/or the
        # owner's text and images. A restart-seal turn holds both at once.
        # Chat Completions tool messages are text-only, so an image a tool returned
        # rides in the user message that follows them.
        tool_images = []
        for block in content:
            if block.get("type") == "tool_result":
                result = block.get("content", "")
                if not isinstance(result, str):
                    tool_images.extend(b for b in result if b["type"] == "image")
                    result = "\n".join(b["text"] for b in result if b["type"] == "text")
                out.append({"role": "tool", "tool_call_id": block["tool_use_id"], "content": result})
        owner = [b for b in content if b.get("type") in ("text", "image")]
        parts = [_user_part(b) for b in [*tool_images, *owner]]
        if parts:
            out.append({"role": "user", "content": parts})
    return out


def _user_part(block):
    if block["type"] == "image":
        source = block["source"]
        return {
            "type": "image_url",
            "image_url": {"url": f"data:{source['media_type']};base64,{source['data']}"},
        }
    return {"type": "text", "text": block["text"]}


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
    text = _CONTROL.sub("", message.get("content") or "")
    if text.strip():
        content.append({"type": "text", "text": text})
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

    def stream_options(self):
        # OpenAI only reports usage on a stream when asked; without it compaction
        # never fires. xAI reports it unasked and overrides this.
        return {"stream_options": {"include_usage": True}}

    async def complete(self, system, messages, tools, model=None, on_text=None):
        gap = self.missing()
        if gap:
            raise RuntimeError(f"{self.name}: not configured ({gap})")

        requested = model or config.MODEL
        body = {"model": requested, "messages": to_messages(system, messages)}
        converted = to_tools(tools)
        if converted:
            body["tools"] = converted

        url = f"{self.base_url()}/chat/completions"
        if on_text:
            data = await self._stream(url, body, on_text)
        else:
            resp = await http.request("POST", url, headers=await self.headers(), json=body)
            if resp.status_code != 200:
                raise ProviderError(self.name, resp.status_code, resp.text)
            data = resp.json()

        self.check_model(requested, data)
        return self.from_response(data)

    async def _stream(self, url, body, on_text):
        body = {**body, "stream": True, **self.stream_options()}
        resp = await http.request("POST", url, headers=await self.headers(), json=body, stream=True)
        try:
            if resp.status_code != 200:
                await resp.aread()
                raise ProviderError(self.name, resp.status_code, resp.text)
            return await self._read_chunks(resp, on_text)
        finally:
            await resp.aclose()

    async def _read_chunks(self, resp, on_text):
        # Reassembled into the non-streaming response shape so from_response and
        # check_model see exactly what they would have without streaming.
        text = ""
        calls = {}
        data = {"usage": {}}
        async for line in resp.aiter_lines():
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            chunk = json.loads(payload)
            if chunk.get("error"):
                raise ProviderError(self.name, 200, json.dumps(chunk["error"]))
            if chunk.get("model"):
                data["model"] = chunk["model"]
            if chunk.get("usage"):
                data["usage"] = chunk["usage"]
            for choice in chunk.get("choices") or []:
                delta = choice.get("delta") or {}
                if delta.get("content"):
                    text += delta["content"]
                    on_text(delta["content"])
                for call in delta.get("tool_calls") or []:
                    slot = calls.setdefault(
                        call["index"],
                        {"id": None, "type": "function", "function": {"name": "", "arguments": ""}},
                    )
                    function = call.get("function") or {}
                    if call.get("id"):
                        slot["id"] = call["id"]
                    if function.get("name"):
                        slot["function"]["name"] = function["name"]
                    if function.get("arguments"):
                        slot["function"]["arguments"] += function["arguments"]

        message = {"content": text, "tool_calls": [calls[i] for i in sorted(calls)]}
        data["choices"] = [{"message": message}]
        return data
