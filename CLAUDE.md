# Kiri

Minimal, un-opinionated personal agent. Runs on the owner's machine, talks over
Discord DM, does exactly what it's asked with whatever tools it's given. Not a
coding agent. See `README.md` for user-facing setup.

The code is small and readable; infer the structure from it. This file is only
the things the code does *not* make obvious — the rules that are easy to break
and the decisions that look like bugs but aren't.

## Hard constraints (do not break)

- **No `anthropic` SDK.** The model loop is hand-rolled over `httpx`. The `mcp`
  SDK is fine — it's how developer MCP servers are loaded.
- **No Anthropic server-side tools** (web search/fetch, etc.). Web search/fetch
  is our own code against Exa.
- **Fail loud, never guess.** On ambiguity or a tool error, stop and surface the
  real error. No silent retries, no papering over failures. This is the one
  engine invariant; everything else about behavior lives in the overridable
  prompt (`engine/default_prompt.md`).
- **No `max_tokens` setting.** Deliberately removed. The Anthropic Messages API
  requires the field, so `providers/anthropic.py` hardcodes a ceiling — that is
  not a budget knob, don't promote it back into config.
- **Never read or commit secrets.** `kiri.toml`, `.env`, `*.db`, `mcp.json` are
  gitignored and hold real credentials.

## Gotchas (these will waste your time)

- **OpenRouter goes through `providers/anthropic.py`, not `openai.py`.** It
  exposes a native Anthropic Messages endpoint, so it reuses that provider with
  only a different URL + auth header. `openai.py` is exclusively for OpenAI and
  OpenAI-compatible `base_url` endpoints. The names are misleading; the routing
  is intentional.
- **Internal message shape is Anthropic content blocks everywhere** (`tool_use`
  / `tool_result` / `text`). Only `openai.py` translates, at the edge. Don't let
  OpenAI-style shapes leak into `engine/`, and keep `engine/` free of outside
  I/O.
- **Compaction must cut on a real user turn.** `context.py:_safe_cut` walks the
  boundary back so the retained tail never starts with an orphan `tool_result`
  (the API rejects a `tool_result` that doesn't follow its `tool_use`). If you
  touch summarization/compaction, preserve that pairing or runs start failing
  only once a conversation is long enough to compact.
- **The scheduler is coarse and reminders self-delete.** `run_scheduler` polls
  every ~20s, so jobs fire within ~20s of their time, not on the second.
  Reminders are jobs with a null `cron`; they fire once and delete themselves.
  Don't assume exact timing or persistent reminders.
- **Natural-language time parsing is the model's job, not the tool's.** The
  `remind` tool only accepts an absolute UTC/ISO time or epoch seconds; `cron`
  is 5-field UTC. Keep NL time parsing in the prompt/model, not in the tool.
- **Any new DM cancels the in-flight run.** `transports/discord/client.py`
  cancels the running task on every message; `stop`/`cancel` are reserved words
  handled before dispatch. One owner only — non-owner and non-DM messages are
  dropped silently.
- **Agent memory is flat files, never sqlite.** Sqlite (`DB_PATH`) is
  harness-only state (sessions, jobs, usage) and the agent never reads it.
  Long-term agent memory lives under `MEMORY_DIR` so the model can `rg`/`cat`/
  write it with the shell. Don't move agent memory into the database.
- **STT is a lazy, optional singleton.** `faster-whisper` is heavy, so it's
  imported and loaded on first voice message and cached process-wide. It decodes
  OGG/Opus itself via bundled PyAV — don't add an ffmpeg shell-out. A missing
  extra surfaces as a clear install hint, not a crash.
- **DB tables auto-register.** Every `_Base` subclass appends itself via
  `__init_subclass__`, and `bind()` creates them all. There is no hand-written
  table list to update when you add a model.

## Conventions

- Config resolution is env > TOML > default, via `config._get`. In example
  config files, comments go **above** the line they describe, never trailing.
- Style: early returns, top-to-bottom, small functions, no docstrings, comment
  only non-obvious logic. Plain-text output, no emojis.
- Tests use no `pytest-asyncio`; drive coroutines with `asyncio.run`. The DB is
  bound to a tmp file per test (see `tests/conftest.py`).

## Commands

```sh
uv sync                 # core deps
uv sync --extra stt     # + on-device voice transcription (faster-whisper)
uv run pytest -q        # tests
uv run kiri             # boot the bot
uv run kiri usage       # token tally (reads sqlite, separate process)
```
