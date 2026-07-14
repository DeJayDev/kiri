import os
import tomllib
from typing import Any

# Config source is a TOML file; environment variables override any value (so
# secrets can live in the shell's .env instead of the file). Resolution order:
# env > TOML > default.


def _load_toml():
    candidates = [os.environ.get("KIRI_CONFIG"), os.path.expanduser("~/.kiri/config.toml"), "kiri.toml"]
    for path in candidates:
        if path and os.path.exists(path):
            with open(path, "rb") as f:
                return tomllib.load(f), path
    return {}, None


_toml, CONFIG_PATH = _load_toml()


def _dig(data, keys) -> Any:
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


_read = set()


def _get(env, default, *toml_keys) -> Any:
    _read.add(toml_keys)
    if env and os.environ.get(env) is not None:
        return os.environ[env]
    value = _dig(_toml, toml_keys)
    return value if value is not None else default


def _paths(data, prefix=()):
    for key, value in data.items():
        path = (*prefix, key)
        if isinstance(value, dict):
            yield from _paths(value, path)
        else:
            yield path


def stale():
    # Every setting reaches the code through _get, so a key it never asks for is a
    # key nothing reads -- a setting the owner believes is in effect and isn't.
    return sorted(path for path in _paths(_toml) if path not in _read)


TRANSPORT = _get("KIRI_TRANSPORT", "discord", "transport", "name").lower()

PROVIDER = _get("KIRI_PROVIDER", "anthropic", "model", "provider").lower()
MODEL = _get("KIRI_MODEL", "claude-opus-4-8", "model", "name")
MODEL_CONTEXT = int(_get("KIRI_MODEL_CONTEXT", 200000, "model", "context_window"))
SUMMARY_MODEL = _get("KIRI_SUMMARY_MODEL", None, "model", "summary_model") or None
SUMMARY_PROVIDER = _get("KIRI_SUMMARY_PROVIDER", None, "model", "summary_provider") or None

# Rolling summarization: compact when an exchange's input tokens exceed
# COMPACT_AT of the context window; keep the last KEEP_RECENT turns verbatim.
COMPACT_AT = float(_get("KIRI_COMPACT_AT", 0.75, "context", "compact_at"))
KEEP_RECENT = int(_get("KIRI_KEEP_RECENT", 6, "context", "keep_recent"))

ANTHROPIC_API_KEY = _get("ANTHROPIC_API_KEY", None, "providers", "anthropic", "api_key")
OPENROUTER_API_KEY = _get("OPENROUTER_API_KEY", None, "providers", "openrouter", "api_key")
OPENAI_API_KEY = _get("OPENAI_API_KEY", None, "providers", "openai", "api_key")
OPENAI_BASE_URL = _get("OPENAI_BASE_URL", None, "providers", "openai", "base_url")

# No default: baking in another product's client_id means impersonating it.
XAI_CLIENT_ID = _get("XAI_CLIENT_ID", None, "providers", "xai", "client_id")
XAI_API_KEY = _get("XAI_API_KEY", None, "providers", "xai", "api_key")

DISCORD_BOT_TOKEN = _get("DISCORD_BOT_TOKEN", None, "discord", "token")
# 0 means unset; require() rejects it.
OWNER_ID = int(_get("KIRI_OWNER_ID", 0, "discord", "owner_id") or 0)

EXA_API_KEY = _get("EXA_API_KEY", None, "web", "exa_api_key")

# Speech-to-text for Discord voice messages, run on-device (no per-use cost).
# Needs the optional `stt` extra installed.
STT_MODEL = _get("KIRI_STT_MODEL", "base", "stt", "model")
STT_DEVICE = _get("KIRI_STT_DEVICE", "cpu", "stt", "device")
STT_COMPUTE_TYPE = _get("KIRI_STT_COMPUTE_TYPE", "int8", "stt", "compute_type")
STT_LANGUAGE = _get("KIRI_STT_LANGUAGE", None, "stt", "language") or None

KIRI_HOME = os.path.expanduser(_get("KIRI_HOME", "~/.kiri", "paths", "home"))
DB_PATH = os.path.expanduser(_get("KIRI_DB", os.path.join(KIRI_HOME, "kiri.db"), "paths", "db"))
# Flat-file long-term memory the agent reads and writes with the shell (rg/cat).
# Deliberately not sqlite: greppable beats a schema the agent has to introspect.
MEMORY_DIR = os.path.expanduser(_get("KIRI_MEMORY_DIR", os.path.join(KIRI_HOME, "memory"), "paths", "memory"))
# Owner-authored procedures, one <name>/SKILL.md each. Their descriptions ride in
# the prompt prefix, so unlike memory these are written by a person, rarely.
SKILLS_DIR = os.path.expanduser(_get("KIRI_SKILLS_DIR", os.path.join(KIRI_HOME, "skills"), "paths", "skills"))
MCP_CONFIG = os.path.expanduser(
    _get("KIRI_MCP_CONFIG", os.path.join(KIRI_HOME, "mcp.json"), "paths", "mcp_config")
)
# OAuth tokens, rewritten on every refresh. Never hand-edited, never committed.
CREDENTIALS_PATH = os.path.expanduser(
    _get("KIRI_CREDENTIALS", os.path.join(KIRI_HOME, "credentials.json"), "paths", "credentials")
)
PROMPT_FILE = _get("KIRI_PROMPT_FILE", None, "paths", "prompt_file") or None

SHELL_OUTPUT_CAP = 30000


def require():
    # Imported here, not at module scope: both import config.
    from kiri import transports
    from kiri.engine import providers

    for path in stale():
        print(f"warning: {CONFIG_PATH} sets {'.'.join(path)}, which kiri does not read")

    missing = []
    for name in {PROVIDER, SUMMARY_PROVIDER} - {None}:
        if name not in providers.PROVIDERS:
            known = ", ".join(providers.PROVIDERS)
            raise SystemExit(f"unknown provider '{name}' (use: {known})")
        gap = providers.PROVIDERS[name]().missing()
        if gap:
            missing.append(gap)

    if TRANSPORT not in transports.TRANSPORTS:
        known = ", ".join(sorted(transports.TRANSPORTS))
        raise SystemExit(f"unknown transport '{TRANSPORT}' (use: {known})")
    gap = transports.TRANSPORTS[TRANSPORT].missing()
    if gap:
        missing.append(gap)

    if missing:
        raise SystemExit(f"missing required config: {', '.join(missing)}")
    os.makedirs(KIRI_HOME, exist_ok=True)
    os.makedirs(MEMORY_DIR, exist_ok=True)
    os.makedirs(SKILLS_DIR, exist_ok=True)
