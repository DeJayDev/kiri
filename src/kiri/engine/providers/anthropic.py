import httpx

from ... import config

# The Messages API requires max_tokens. It's not a user-facing knob; this is a
# generous ceiling for a non-streaming chat reply, not a budget to tune.
_MAX_TOKENS = 16000


def _endpoint():
    # OpenRouter exposes a native Anthropic Messages endpoint, so it shares this
    # provider with no translation; only the URL and auth differ.
    if config.PROVIDER == "openrouter":
        key = config.OPENROUTER_API_KEY
        headers = {"authorization": f"Bearer {key}", "content-type": "application/json"}
        return "https://openrouter.ai/api/v1/messages", headers, key

    key = config.ANTHROPIC_API_KEY
    headers = {
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    return "https://api.anthropic.com/v1/messages", headers, key


async def complete(system, messages, tools):
    url, headers, key = _endpoint()
    if not key:
        raise RuntimeError(f"{config.PROVIDER}: api key not set")

    body = {
        "model": config.MODEL,
        "max_tokens": _MAX_TOKENS,
        "system": system,
        "messages": messages,
    }
    if tools:
        body["tools"] = tools

    async with httpx.AsyncClient(timeout=httpx.Timeout(600.0)) as client:
        resp = await client.post(url, headers=headers, json=body)

    if resp.status_code != 200:
        raise RuntimeError(f"{config.PROVIDER} {resp.status_code}: {resp.text}")
    # Already canonical: content blocks, stop_reason, usage.
    return resp.json()
