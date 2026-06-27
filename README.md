# Kiri

Kiri is a personal agent you host yourself. It runs as a small process on your
own machine, talks to you privately over a Discord DM, and acts through the
tools you give it: your shell, web search, and any MCP servers you wire in.

## Why Kiri exists

Most AI assistants run in someone else's cloud. They are multi-tenant and
sandboxed, locked to one vendor, wrapped in product features and guardrails, and
limited to the integrations the vendor decided to ship. That is the right
trade-off for a mass-market app, and the wrong one if what you actually want is
an agent that can touch *your* machine and *your* tools.

Kiri takes the opposite position on every one of those choices:

- **It runs on your hardware, not in a sandbox.** Its main tool is a real shell
  with your full `PATH`, so it can use the CLIs and scripts you already have.
- **You bring the model.** Point it at Anthropic, OpenRouter, or any
  OpenAI-compatible endpoint. One model, your key, your bill.
- **It ships extensibility, not integrations.** There are no built-in app
  connectors. Its capabilities are whatever you put on the machine and whatever
  MCP servers you connect.
- **It is yours alone.** One owner, private over DM. It ignores everyone else.
- **It does what you ask and fails loud.** When something is ambiguous or a tool
  errors, it stops and tells you instead of guessing or quietly papering over
  the failure.

If you want a polished assistant that works out of the box for everyone, Kiri is
not it. If you want a private agent that is small enough to read in an afternoon
and does exactly what you wire it to do, that is the whole idea.

## Who it's for

Anyone curious about running their own agent. You will be most comfortable if
you can edit a config file and run a command in a terminal, but you do not need
to understand the internals to use it.

## Features

- Private, owner-only Discord DM interface
- Anthropic, OpenRouter, and OpenAI-compatible providers
- Shell access through your machine's `PATH`
- Web search and fetch (via Exa)
- MCP servers loaded from your own config
- Optional on-device transcription of Discord voice messages
- Recurring jobs and one-shot reminders
- Conversation memory that survives restarts, plus flat-file long-term memory
- Token usage tracking

## Setup

You need [`uv`](https://docs.astral.sh/uv/) and Python 3.14 or newer.

```sh
git clone https://github.com/DeJayDev/kiri.git
cd kiri
cp kiri.example.toml kiri.toml
uv sync
uv run kiri
```

Then fill in `kiri.toml`:

- `[model] provider` and `name`
- the API key for that provider
- `[discord] token`
- `[discord] owner_id` (your numeric Discord user ID)
- optional `[web] exa_api_key` to enable web search and fetch

Config is read from `$KIRI_CONFIG`, then `~/.kiri/config.toml`, then
`./kiri.toml`. Environment variables override any value in the file, so you can
keep secrets out of it. Every key is documented in `kiri.example.toml` and
`.env.example`.

### Discord

Create a bot in the Discord developer portal, enable the **Message Content
Intent**, and DM the bot from the account whose ID you set as `owner_id`. Kiri
responds to that account only.

### MCP servers

Point `[paths] mcp_config` (or `KIRI_MCP_CONFIG`) at a JSON file shaped like
`mcp.example.json` to add MCP tools.

### Voice messages

Transcription runs on-device and is an optional extra:

```sh
uv sync --extra stt
```

## Running persistently

Kiri is a long-running process, and its scheduler only fires while it is up, so
run it under a supervisor if you rely on reminders or recurring jobs.

On Linux, use the systemd user service in `deploy/kiri.service`:

```sh
mkdir -p ~/.config/systemd/user
cp deploy/kiri.service ~/.config/systemd/user/kiri.service
# adjust WorkingDirectory and EnvironmentFile if needed
systemctl --user daemon-reload
systemctl --user enable --now kiri
loginctl enable-linger "$USER"
journalctl --user -u kiri -f
```

For reminders and jobs to fire reliably, host Kiri somewhere that stays awake,
such as a VPS, a Raspberry Pi, or a home server.

## Usage

DM the bot and it replies. Send `stop` to abort a run in progress.

```sh
uv run kiri          # start the bot
uv run kiri usage    # print token usage
uv run pytest -q     # run the tests
```

## Contributing

Kiri is small on purpose. Architecture notes and the constraints worth knowing
before you change anything live in `CLAUDE.md`.
