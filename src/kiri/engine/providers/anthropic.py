import json

from kiri import config, http
from kiri.engine.providers.base import Provider, ProviderError, normalize_usage

# The Messages API requires max_tokens; it is not a user-facing knob.
_MAX_TOKENS = 16000

_CACHE = {"type": "ephemeral", "ttl": "1h"}


def _system_blocks(system):
    segments = [system] if isinstance(system, str) else list(system)
    blocks = [{"type": "text", "text": text} for text in segments if text]
    # Render order is tools -> system -> messages, so this one breakpoint caches
    # the tool schemas too.
    if blocks:
        blocks[-1] = {**blocks[-1], "cache_control": _CACHE}
    return blocks


def _messages(messages):
    if not messages:
        return messages

    head, last = messages[:-1], messages[-1]
    content = last["content"]
    blocks = [{"type": "text", "text": content}] if isinstance(content, str) else list(content)
    if not blocks:
        return messages

    # Rebuilt, not mutated: session history must stay free of cache_control so it
    # round-trips through sqlite and the openai translator.
    blocks = [*blocks[:-1], {**blocks[-1], "cache_control": _CACHE}]
    return [*head, {**last, "content": blocks}]


class Anthropic(Provider):
    name = "anthropic"
    url = "https://api.anthropic.com/v1/messages"

    def key(self):
        return config.ANTHROPIC_API_KEY

    def missing(self):
        return None if self.key() else f"{self.name} api key"

    async def headers(self):
        return {
            "x-api-key": self.key(),
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

    async def complete(self, system, messages, tools, model=None, on_text=None):
        gap = self.missing()
        if gap:
            raise RuntimeError(f"{self.name}: not configured ({gap})")

        body = {
            "model": model or config.MODEL,
            "max_tokens": _MAX_TOKENS,
            "system": _system_blocks(system),
            "messages": _messages(messages),
        }
        if tools:
            body["tools"] = tools

        if on_text:
            data = await self._stream(body, on_text)
        else:
            resp = await http.request("POST", self.url, headers=await self.headers(), json=body)
            if resp.status_code != 200:
                raise ProviderError(self.name, resp.status_code, resp.text)
            data = resp.json()

        usage = data.get("usage", {})
        data["usage"] = normalize_usage(
            usage.get("input_tokens", 0),
            usage.get("output_tokens", 0),
            cache_read=usage.get("cache_read_input_tokens", 0),
            cache_write=usage.get("cache_creation_input_tokens", 0),
        )
        return data

    async def _stream(self, body, on_text):
        resp = await http.request(
            "POST", self.url, headers=await self.headers(), json={**body, "stream": True}, stream=True
        )
        try:
            if resp.status_code != 200:
                await resp.aread()
                raise ProviderError(self.name, resp.status_code, resp.text)
            return await self._read_events(resp, on_text)
        finally:
            await resp.aclose()

    async def _read_events(self, resp, on_text):
        message = {}
        partial_json = {}
        async for line in resp.aiter_lines():
            if not line.startswith("data:"):
                continue
            event = json.loads(line[5:])
            kind = event["type"]
            if kind == "message_start":
                message = event["message"]
            elif kind == "content_block_start":
                message["content"].append(event["content_block"])
            elif kind == "content_block_delta":
                index = event["index"]
                block = message["content"][index]
                delta = event["delta"]
                if delta["type"] == "text_delta":
                    block["text"] += delta["text"]
                    on_text(delta["text"])
                elif delta["type"] == "input_json_delta":
                    partial_json[index] = partial_json.get(index, "") + delta["partial_json"]
                elif delta["type"] == "thinking_delta":
                    block["thinking"] += delta["thinking"]
                elif delta["type"] == "signature_delta":
                    block["signature"] = delta["signature"]
                else:
                    raise ProviderError(self.name, 200, f"unknown stream delta: {json.dumps(delta)}")
            elif kind == "content_block_stop":
                index = event["index"]
                if index in partial_json:
                    message["content"][index]["input"] = json.loads(partial_json.pop(index) or "{}")
            elif kind == "message_delta":
                message.update(event["delta"])
                # Cumulative counts; a field the event leaves null keeps message_start's value.
                usage = {k: v for k, v in event.get("usage", {}).items() if v is not None}
                message["usage"] = {**message.get("usage", {}), **usage}
            elif kind == "error":
                raise ProviderError(self.name, 200, json.dumps(event["error"]))
        return message


class OpenRouter(Anthropic):
    name = "openrouter"
    url = "https://openrouter.ai/api/v1/messages"

    def key(self):
        return config.OPENROUTER_API_KEY

    async def headers(self):
        return {"authorization": f"Bearer {self.key()}", "content-type": "application/json"}
