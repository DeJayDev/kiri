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

    async def complete(self, system, messages, tools, model=None):
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


class OpenRouter(Anthropic):
    name = "openrouter"
    url = "https://openrouter.ai/api/v1/messages"

    def key(self):
        return config.OPENROUTER_API_KEY

    async def headers(self):
        return {"authorization": f"Bearer {self.key()}", "content-type": "application/json"}
