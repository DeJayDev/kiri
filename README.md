# Kiri

Minimal, un-opinionated personal agent. Runs on your machine, talks to you over
Discord DM, and does exactly what you ask using whatever tools you give it.

Kiri is not a cloud service, coding-agent framework, or bundle of prebuilt app
integrations. It is a small private harness for one owner, one model, local
tools, web search, MCP servers, reminders, and memory.

## Features

- Owner-only Discord DM interface
- Anthropic, OpenRouter, and OpenAI-compatible providers
- Local shell access through your `PATH`
- Exa-backed `web_search` / `web_fetch`
- MCP server loading from your own config
- Optional on-device voice-message transcription
- Recurring jobs, one-shot reminders, and `stop` to abort a run
- Rolling DM context, flat-file long-term memory, and token usage tracking

## Setup

```sh
git clone https://github.com/DeJayDev/kiri.git
cd kiri
cp kiri.example.toml kiri.toml
uv sync
uv run kiri
```

Fill in `kiri.toml`:

- `[model] provider` and `name`
- the matching provider API key
- `[discord] token`
- `[discord] owner_id`
- optional `[web] exa_api_key` for web tools

Config is loaded from `$KIRI_CONFIG`, then `~/.kiri/config.toml`, then
`./kiri.toml`. Environment variables override TOML values, so secrets can stay
out of the config file. See `kiri.example.toml` and `.env.example` for every key.

For Discord, create a bot, enable **Message Content Intent**, and DM it from the
account whose numeric user ID is `owner_id`. Kiri ignores everyone else.

For MCP, point `[paths] mcp_config` or `KIRI_MCP_CONFIG` at a JSON file shaped
like `mcp.example.json`.

For voice-message transcription:

```sh
uv sync --extra stt
```

## Running persistently

Kiri is a long-running process. The scheduler only fires while it is running, so
put it under a supervisor for reminders and recurring jobs.

On Linux, use the systemd user service in `deploy/kiri.service`:

```sh
mkdir -p ~/.config/systemd/user
cp deploy/kiri.service ~/.config/systemd/user/kiri.service
# edit WorkingDirectory and EnvironmentFile if needed
systemctl --user daemon-reload
systemctl --user enable --now kiri
loginctl enable-linger "$USER"
journalctl --user -u kiri -f
```

On WSL2, systemd can work, but WSL is not truly always-on. Scheduled jobs will
not fire when Windows sleeps or WSL stops. For real persistence, run Kiri on a
VPS, Pi, home server, or anything else that stays awake like an adult.

## Commands

```sh
uv run kiri          # start the bot
uv run kiri usage    # print token usage
uv run pytest -q     # run tests
```

## Notes

- Requires Python `>=3.14` and `uv`.
- Long-term memory lives in flat files under `~/.kiri/memory`.
- Harness state such as sessions, jobs, and usage lives in sqlite.
- Development constraints and architecture notes live in `CLAUDE.md`.
