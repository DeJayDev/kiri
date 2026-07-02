from typing import Any

from kiri import config
from kiri.engine.providers import anthropic, openai


async def complete(system, messages, tools) -> dict[str, Any]:
    # Internal message/content shape is Anthropic-canonical. anthropic + openrouter
    # speak it natively (no translation); the openai provider translates to/from
    # OpenAI chat format for any OpenAI-compatible endpoint.
    if config.PROVIDER in ("anthropic", "openrouter"):
        return await anthropic.complete(system, messages, tools)
    return await openai.complete(system, messages, tools)
