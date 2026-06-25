# Kiri

A minimal, un-opinionated personal agent. Runs on your machine, talks to you
over Discord DM, does exactly what you ask using whatever tools you give it.
Ships extensibility, not integrations.

## What it is

- Raw, hand-rolled model loop (no Anthropic SDK). One model you choose.
- Pluggable provider: `anthropic` and `openrouter` both speak the canonical
  Anthropic Messages format natively (no translation); `openai` translates for
  any OpenAI-compatible endpoint.
- Discord DM transport, owner-only.
- Capabilities: shell + your PATH binaries, web search/fetch (Exa), and any MCP
  servers you wire in. No baked-in app integrations.
- Rolling-summary context per DM. Opt-in scheduled jobs. `stop` to abort a run.
- One hard rule baked into the engine: fail loud, never guess. Everything else
  lives in the (overridable) system prompt at `src/kiri/engine/default_prompt.md`.

## Setup

```sh
cp kiri.example.toml kiri.toml     # fill it in
uv sync
uv run kiri
```

Config is TOML, looked up at `$KIRI_CONFIG`, then `~/.kiri/config.toml`, then
`./kiri.toml`. **Any value can be overridden by an environment variable** (env
wins), so secrets can stay in your shell's `.env` while the rest lives in the
file. See `kiri.example.toml` for every key.

Required: a provider api key (matching `[model] provider`), `[discord] token`,
and `[discord] owner_id`. Optional: `[web] exa_api_key` for the web tools.

**Provider:** set `[model] provider`. For OpenRouter, use a model slug like
`anthropic/claude-3.7-sonnet` and put the key in `[providers.openrouter]`
(or `OPENROUTER_API_KEY`).

**Discord:** create a bot, enable the **Message Content Intent** in the developer
portal, and DM it from the account whose id is `owner_id`. It ignores everyone
and everywhere else.

**MCP:** point `[paths] mcp_config` at a JSON file shaped like `mcp.example.json`.

## Running persistently

It's a long-running process (the in-process scheduler only fires while it's up),
so put it under a supervisor. On a normal always-on Linux box, a systemd **user**
service is the move — see `deploy/kiri.service`:

```sh
cp deploy/kiri.service ~/.config/systemd/user/kiri.service
systemctl --user daemon-reload
systemctl --user enable --now kiri
loginctl enable-linger "$USER"     # survive having no login session
journalctl --user -u kiri -f       # logs
```

On **WSL2** (your case): systemd works if you set `systemd=true` under `[boot]`
in `/etc/wsl.conf`, but WSL is not truly always-on — it stops when Windows sleeps
or the last session closes, so scheduled jobs won't fire then. For real
persistence, host Kiri on something that stays up (a VPS, a Pi, a home server).
`tmux`/`nohup` work for a quick run but won't restart on crash or reboot.

## Layout

```
src/kiri/
  app.py              startup wiring (the only place layers meet)
  config.py
  mcp_client.py       loads developer MCP servers (mcp SDK)
  engine/             the brain: no outside I/O
    llm.py            facade over the providers + text helper
    providers/        anthropic.py, openai.py (openrouter/openai-compatible)
    agent.py          the tool-use loop
    context.py        per-DM session + rolling summarization
    sessions.py       one rolling session per channel
    conversation.py   run_turn(): shared path for DMs and jobs
    prompt.py
    default_prompt.md  the baked, overridable behavior
  transports/         how you reach it (pluggable)
    discord/
      client.py       gateway, owner gate, interrupt, typing
      output.py       rendering: chunk-or-file
  tools/              capabilities
    shell.py
    web.py            Exa search + fetch
  scheduling/         durable jobs, one concern
    store.py          sqlite store + in-process scheduler
    tool.py           schedule / list / cancel tools
```
