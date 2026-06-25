# Kiri

Minimal, un-opinionated personal agent. Runs on the owner's machine, talks over
Discord DM, does exactly what it's asked with whatever tools it's given. Not a
coding agent. See `README.md` for user-facing setup.

## Hard constraints (do not break)

- **No `anthropic` SDK** — the model loop is hand-rolled over `httpx`. The `mcp`
  SDK is fine; it's how developer MCP servers are loaded.
- **No Anthropic server-side tools** (web search/fetch, etc.). Web search/fetch
  is our own code against Exa.
- **One engine rule is non-negotiable: fail loud, never guess.** On ambiguity or
  a tool error, stop and surface the real error. Don't silently retry or paper
  over failures. Everything else about behavior lives in the overridable prompt.
- **Never commit secrets.** `kiri.toml`, `.env`, `*.db`, `mcp.json` are
  gitignored and carry real credentials. Don't read or stage them.

## Architecture

- Internal message shape is **Anthropic content blocks** (`tool_use` /
  `tool_result` / `text`) everywhere. `engine/` is provider-agnostic and does no
  outside I/O.
- Providers: `anthropic` and `openrouter` speak the canonical Anthropic Messages
  format natively (no translation); `openrouter` just swaps the endpoint + auth
  header. `openai` translates to/from `/chat/completions`.
- `engine/conversation.py:run_turn` is the single path shared by live DMs and
  scheduled jobs.
- `app.py` is the only place the layers are wired together.
- **Storage split:** harness state (sessions, jobs, usage) lives in sqlite at
  `DB_PATH`; the agent never reads it. Agent-facing long-term memory is flat
  files under `MEMORY_DIR` (`~/.kiri/memory`) — the model uses the shell on it
  (`rg`/`cat`/write), no schema. Don't put agent memory in sqlite.
- Scheduling: recurring = cron jobs; one-shot = reminders (nullable `cron`,
  self-delete after firing). The model parses NL time into an absolute UTC
  timestamp; the `remind` tool only takes the timestamp.
- Usage tokens are recorded via an `on_usage` sink threaded through `run_turn`,
  so the engine stays import-pure. `kiri usage` reads the tally back out.

## Conventions

- Config: TOML with env override (env > TOML > default), via `config._get`.
  There is **no `max_tokens` setting** — deliberately removed; don't add one.
- In example config files, comments go **above** the line they describe, never
  trailing.
- Style: early returns, top-to-bottom, small functions, no docstrings, comment
  only non-obvious logic. Plain-text output, no emojis.

## Commands

```sh
uv sync                 # core deps
uv sync --extra stt     # + on-device voice transcription (faster-whisper)
uv run pytest -q        # tests (no pytest-asyncio; use asyncio.run)
uv run kiri             # boot the bot
uv run kiri usage       # token tally (reads sqlite, separate process)
```
