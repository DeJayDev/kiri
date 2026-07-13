# Kiri

Minimal, un-opinionated personal agent. Runs on the owner's machine, talks over
Discord DM, does exactly what it's asked with whatever tools it's given. Not a
coding agent. See `README.md` for setup and the full layout.

This file is rules, not notes. Every line is something you can be held to.

## Hard constraints (never break)

- **Never edit this file to fit code you just wrote.** The rules are the owner's.
  If one blocks you, say so and stop — don't rewrite it, don't add a clause that
  makes your change legal. Changes here are their own task, asked for on purpose.
- **No `anthropic` SDK.** The model loop is hand-rolled over `httpx`. The `mcp`
  SDK is fine; it's how MCP servers are loaded.
- **No Anthropic server-side tools** (web search/fetch, etc.). Web search and
  fetch are our own code against Exa.
- **Fail loud, never guess.** Surface the real error. Retrying a 429 or a dropped
  socket is not a guess; papering over a 400, a bad key, or a malformed response
  is. Carry the status — never diagnose by string-matching an error message.
- **Never commit secrets.** `kiri.toml`, `.env`, `*.db`, `mcp.json`,
  `credentials.json` are gitignored and hold real credentials. Don't read or
  stage them.
- **Storage split.** Harness state (sessions, jobs, usage) in sqlite at
  `DB_PATH`; the agent never reads it. Agent memory is flat files under
  `MEMORY_DIR` — the model greps them with the shell, no schema. Don't put agent
  memory in sqlite. OAuth tokens live in `credentials.json` (0600), not sqlite:
  recovery from a bad token must be "delete the file".
- **Anthropic content blocks** (`tool_use` / `tool_result` / `text`) are the
  internal message shape everywhere. `engine/` is provider-agnostic and does no
  outside I/O — providers and the usage sink are injected at boot.

## The model is the feature. The harness is plumbing.

Kiri hands a capable model a shell and gets out of the way. A model that adapts
beats a harness that guessed. Before you add code, ask whether the model could
just do it:

- Needs the time? It runs `date`. Only the **date** is in context, not a clock.
  Do not add a clock.
- Needs a file's contents, a command's output, what's installed? It has a shell.
- Needs a capability we don't have? That's an MCP server, not a new tool.
- Needs to decide how long something should take, or how much of something to
  do? It decides. If it doesn't say, pick one value and hardcode it.

The agent loop is `while True` **on purpose**. Not capped, not budgeted, not
policed. An agent that loops until it's done is what an agent *is*. If it spins,
that's a prompt problem — and `stop` exists.

## Don't add what you don't need

- **No config knob nobody sets.** If the wrong value costs cents and the right
  one is obvious, hardcode it. Cache TTL, retry backoff, shell timeout: literals.
  A knob that exists only so the code can read it back is not a feature.
- **No named constant for a value used once.** Inline it.
- **No abstraction with one implementation.** A seam earns its place when
  something has a lifecycle the current shape can't hold. "It might be useful
  later" doesn't.
- **No scaffolding for the model's benefit.** No "after N tool calls, summarize",
  no forced progress notes, no context precomputed that it could fetch itself.
- **Use the library the way it expects.** Peewee has migrations; don't hand-roll
  reflection over the models. Reach for the boring documented path first.
- Deleting beats adding. Fix the root cause, not the symptom the report named.

## Comments, and text the model reads

- Comments go **above** the line, never trailing.
- **In code:** comment only an invariant that silently breaks if violated. Not
  what the line does. Not why you picked it. Not a note to the reviewer, not a
  summary of your diff. If you can't name what breaks without it, delete it.
  Commentary is the default failure — write less than feels right.
- **In the example configs** (`kiri.example.toml`, `mcp.example.json`) the rule
  inverts. The reader is a person setting Kiri up, not a maintainer reading code.
  Say what a value means when its name doesn't (`int8` is the fast CPU default;
  `cpu | cuda`; which env var overrides it). These files are the only place that
  knowledge is written down — don't strip it as noise.
- **Text the model reads** — tool descriptions, tool error strings — is a prompt
  and is allowed to be one. Write it like one: the fact, and the single action
  that follows from it, in a sentence or two. No lecture, no apology, no
  instructions for a situation the model can't do anything about.

## Style

- Early returns, top-to-bottom, small functions, no docstrings.
- Plain-text output. No emojis.
- Config: TOML with env override (env > TOML > default), via `config._get`.
  There is **no `max_tokens` setting** — deliberately removed; don't add one.
- Tests: no `pytest-asyncio`; use `asyncio.run`.

## Caching (do not regress this)

Prompt caching is a **prefix match**. One changed byte anywhere in the prefix
invalidates everything after it. Render order is `tools` → `system` → `messages`.

- Nothing per-request may appear in `Session.system()`. A `datetime.now()` there
  once made the cache unhittable.
- `input_tokens` is the *uncached remainder*. True context size is
  `input + cache_read + cache_write` — `record_usage` must sum all three or
  compaction never fires.
- Providers normalize usage so "input" means uncached everywhere.

## Commands

```sh
uv sync                     # core deps
uv sync --extra stt         # + on-device voice transcription (faster-whisper)
uv run pytest -q            # tests
uv run kiri                 # boot (transport from config; KIRI_TRANSPORT=terminal for a repl)
uv run kiri usage           # token tally + cache hit rate
uv run kiri auth status     # provider credentials
uv run kiri auth login xai  # device-code oauth
uv run kiri mcp             # remote mcp servers + auth state
uv run kiri mcp <server>    # authorize one (browser)
```
