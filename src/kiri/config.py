import os
import tomllib

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


def _dig(data, keys):
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def _get(env, default, *toml_keys):
    if env and os.environ.get(env) is not None:
        return os.environ[env]
    value = _dig(_toml, toml_keys)
    return value if value is not None else default


PROVIDER = _get("KIRI_PROVIDER", "anthropic", "model", "provider").lower()
MODEL = _get("KIRI_MODEL", "claude-opus-4-8", "model", "name")
MODEL_CONTEXT = int(_get("KIRI_MODEL_CONTEXT", 200000, "model", "context_window"))

# Rolling summarization: compact when an exchange's input tokens exceed
# COMPACT_AT of the context window; keep the last KEEP_RECENT turns verbatim.
COMPACT_AT = float(_get("KIRI_COMPACT_AT", 0.75, "context", "compact_at"))
KEEP_RECENT = int(_get("KIRI_KEEP_RECENT", 6, "context", "keep_recent"))

ANTHROPIC_API_KEY = _get("ANTHROPIC_API_KEY", None, "providers", "anthropic", "api_key")
OPENROUTER_API_KEY = _get("OPENROUTER_API_KEY", None, "providers", "openrouter", "api_key")
OPENAI_API_KEY = _get("OPENAI_API_KEY", None, "providers", "openai", "api_key")
OPENAI_BASE_URL = _get("OPENAI_BASE_URL", None, "providers", "openai", "base_url")

DISCORD_BOT_TOKEN = _get("DISCORD_BOT_TOKEN", None, "discord", "token")
_owner = _get("KIRI_OWNER_ID", None, "discord", "owner_id")
OWNER_ID = int(_owner) if _owner else None

EXA_API_KEY = _get("EXA_API_KEY", None, "web", "exa_api_key")

KIRI_HOME = os.path.expanduser(_get("KIRI_HOME", "~/.kiri", "paths", "home"))
DB_PATH = os.path.expanduser(_get("KIRI_DB", os.path.join(KIRI_HOME, "kiri.db"), "paths", "db"))
MCP_CONFIG = os.path.expanduser(
    _get("KIRI_MCP_CONFIG", os.path.join(KIRI_HOME, "mcp.json"), "paths", "mcp_config")
)
PROMPT_FILE = _get("KIRI_PROMPT_FILE", None, "paths", "prompt_file") or None

DISCORD_LIMIT = 2000
SHELL_OUTPUT_CAP = 30000

_PROVIDER_KEYS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "openai": "OPENAI_API_KEY",
}


def provider_key():
    return globals().get(_PROVIDER_KEYS.get(PROVIDER, ""))


def require():
    missing = []
    if PROVIDER not in _PROVIDER_KEYS:
        raise SystemExit(f"Unknown provider '{PROVIDER}' (use: {', '.join(_PROVIDER_KEYS)})")
    if not provider_key():
        missing.append(f"{PROVIDER} api key")
    if not DISCORD_BOT_TOKEN:
        missing.append("discord token")
    if not OWNER_ID:
        missing.append("discord owner_id")
    if missing:
        raise SystemExit(f"Missing required config: {', '.join(missing)}")
    os.makedirs(KIRI_HOME, exist_ok=True)
