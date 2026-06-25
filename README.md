# Kiri

Kiri is a minimal personal agent that runs on your machine and talks to you over Discord DM. It is intentionally un-opinionated: one owner, one model, the tools you choose, and no baked-in SaaS integrations.

It is not a coding agent framework or a cloud service. It is a small harness for giving a private agent access to your shell, web search, MCP servers, reminders, and flat-file memory.

## What you get

- Owner-only Discord DM interface. Kiri ignores every other user and channel.
- Hand-rolled model loop over `httpx`; no `anthropic` SDK and no Anthropic server-side tools.
- Providers for Anthropic, OpenRouter, and OpenAI-compatible chat endpoints.
- Shell access through your local `PATH`, Exa-backed `web_search` / `web_fetch`, and any MCP servers you configure.
- Optional on-device transcription for Discord voice messages with `faster-whisper`.
- Rolling conversation context stored in sqlite, so DM sessions survive restarts.
- Recurring cron jobs and one-shot reminders, driven by the same conversation engine as live DMs.
- Long-term memory as plain files under `~/.kiri/memory`, read and written by the agent with normal shell tools.
- Token usage accounting with `kiri usage`.

The engine has one hard-coded behavior rule: fail loud, never guess. If a request is ambiguous or a tool errors, Kiri surfaces that instead of silently inventing a workaround. Everything else lives in the overridable system prompt at `src/kiri/engine/default_prompt.md`.

## Requirements

- Python `>=3.14`
- [`uv`](https://docs.astral.sh/uv/)
- A Discord bot token with Message Content Intent enabled
- A model provider key for Anthropic, OpenRouter, or an OpenAI-compatible endpoint
- Optional: an Exa API key for web tools

## Quick start

```sh
git clone https://github.com/DeJayDev/kiri.git
cd kiri
cp kiri.example.toml kiri.toml
uv sync
uv run kiri
```

Then fill in `kiri.toml` with:

- `[model] provider` and `name`
- the matching provider API key
- `[discord] token`
- `[discord] owner_id`
- optional `[web] exa_api_key`

For voice-message transcription:

```sh
uv sync --extra stt
```

## Configuration

Kiri loads config in this order:

1. `$KIRI_CONFIG`
2. `~/.kiri/config.toml`
3. `./kiri.toml`

Environment variables override TOML values, so secrets can live in your shell or `.env` while the rest stays in `kiri.toml`. See `kiri.example.toml` and `.env.example` for the full key list.

Common provider setups:

```toml
[model]
provider = "anthropic"
name = "claude-opus-4-8"

[providers.anthropic]
api_key = ""
```

```toml
[model]
provider = "openrouter"
name = "anthropic/claude-3.7-sonnet"

[providers.openrouter]
api_key = ""
```

```toml
[model]
provider = "openai"
name = "gpt-4.1"

[providers.openai]
api_key = ""
base_url = ""
```

## Discord setup

1. Create a Discord application and bot in the developer portal.
2. Enable **Message Content Intent** for the bot.
3. Invite the bot somewhere it can receive your DMs.
4. Set `[discord] token` to the bot token.
5. Set `[discord] owner_id` to your numeric Discord user ID.

Kiri only responds to that owner ID. Everyone else is ignored.

## Tools and MCP

Kiri ships with a small default tool surface:

- `shell`: run commands on the host machine
- `web_search` and `web_fetch`: Exa-backed web tools, enabled when `EXA_API_KEY` or `[web] exa_api_key` is set
- scheduling tools for recurring jobs and one-shot reminders

To add MCP servers, point `[paths] mcp_config` or `KIRI_MCP_CONFIG` at a JSON file shaped like `mcp.example.json`:

```json
{
  "servers": {
    "todoist": {
      "command": "npx",
      "args": ["-y", "@some/todoist-mcp"],
      "env": { "TODOIST_API_KEY": "..." }
    }
  }
}
```

## Running persistently

Kiri is a long-running process. The in-process scheduler only fires while it is running, so use a supervisor for reminders and recurring jobs.

On a normal always-on Linux machine, use the systemd user service in `deploy/kiri.service`:

```sh
mkdir -p ~/.config/systemd/user
cp deploy/kiri.service ~/.config/systemd/user/kiri.service
# edit WorkingDirectory and EnvironmentFile if your checkout is not ~/empty
systemctl --user daemon-reload
systemctl --user enable --now kiri
loginctl enable-linger "$USER"
journalctl --user -u kiri -f
```

On WSL2, systemd works if you set `systemd=true` under `[boot]` in `/etc/wsl.conf`, but WSL is not truly always-on. It stops when Windows sleeps or the last session closes, so scheduled jobs will not fire then. For real persistence, run Kiri on something that stays up, like a VPS, Raspberry Pi, or home server.

## Day-to-day commands

```sh
uv run kiri          # start the Discord bot
uv run kiri usage    # print token usage
uv run pytest -q     # run tests
```

When a run is in progress, send `stop` in DM to abort it.

## Project layout

```text
src/kiri/
  app.py              startup wiring; the only place layers meet
  config.py           TOML + environment config
  db.py               sqlite binding
  mcp_client.py       developer MCP server loading
  usage.py            token tally reporting
  engine/             provider-agnostic conversation engine
    agent.py          tool-use loop
    context.py        rolling summary context
    conversation.py   shared run_turn() path for DMs and jobs
    default_prompt.md baked, overridable behavior prompt
    llm.py            provider facade
    providers/        Anthropic, OpenAI, OpenRouter-compatible clients
    sessions.py       one rolling session per channel
  transports/
    discord/          gateway, owner gate, interrupt, output rendering
  tools/
    shell.py
    web.py            Exa search and fetch
  scheduling/
    store.py          durable sqlite jobs + in-process scheduler
    tool.py           schedule, list, and cancel tools
```

Harness state such as sessions, jobs, and usage lives in sqlite at `DB_PATH`. Agent-facing long-term memory is deliberately separate: flat files under `MEMORY_DIR`, usually `~/.kiri/memory`.

## Development

```sh
uv sync
uv run pytest -q
```

Optional STT dependencies:

```sh
uv sync --extra stt
```

Design constraints worth preserving:

- Keep `engine/` provider-agnostic and free of outside I/O.
- Do not add a `max_tokens` config setting.
- Do not commit `kiri.toml`, `.env`, `*.db`, or MCP files containing credentials.
- Keep comments in example config files above the lines they describe.
