from kiri.engine.providers import (  # noqa: F401  -- registers them
    anthropic,
    openai,
    xai,
)
from kiri.engine.providers.base import PROVIDERS


def build(name):
    if name not in PROVIDERS:
        raise SystemExit(f"Unknown provider '{name}' (use: {', '.join(sorted(PROVIDERS))})")
    return PROVIDERS[name]()
