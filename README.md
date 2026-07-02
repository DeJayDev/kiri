# Kiri

A personal agent that actually works. It runs on your hardware - sandboxed or otherwise and prefers to use whatever the machine already has.

To do this, Kiri does not provide any integrations. Its primary tool is the shell — your CLIs, your scripts, whatever is on your PATH and/or any MCP servers of your choice.

## Features

- **Web search and fetch**, powered by Exa. Requires API Key.
- **Scheduling** Recurring jobs and one-shot reminders.
- **Voice messages**, transcribed on-device with faster-whisper: Install with `uv sync --extra stt`.
- **Memory** Kiri conversations are rolling, similar to one long Claude Code session. Messages from the past are automatically summarized. Long-term memory is separate: plain files in `~/.kiri/memory` that Kiri writes and reads itself — greppable, editable, no schema.
- **Followups** While Kiri is working on a task, any messages you send will trigger a follow up - not interrupt her. To stop Kiri just say `stop`.
- **Model portability** Use any Anthropic, OpenRouter, or any OpenAI-compatible endpoint.
- **MCP** Drop a standard server config at `~/.kiri/mcp.json`
  (`mcp.example.json` shows the shape).

## Setup

```sh
cp kiri.example.toml kiri.toml
uv sync
uv run kiri
```

Three things are required: a provider api key, a Discord bot token, and your Discord user id as `owner_id`. Every key is documented in `kiri.example.toml`.

For the bot: create one in the [Discord developer portal](https://discord.com/developers/applications), you will need the **Message Content Intent**.

Scheduled jobs only fire while Kiri is running, so recommended to use systemd (or Docker!) I've provided a systemd service at `deploy/kiri.service` and a `Dockerfile` — add the CLIs you want Kiri to have to its apt-get layer.

## Development

```sh
uv run pytest -q
```
