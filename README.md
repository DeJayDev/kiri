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
- **Skills** Procedures Kiri reads before doing the thing they cover, so she isn't rediscovering your CLI's flags — or repeating the mistake that cost you an evening — every session. A few ship with Kiri; write your own as one `<name>/SKILL.md` in `~/.kiri/skills`. Only the one-line description stays in context; the body is read on demand. Invoke one yourself with `/<name>`.
- **Plugins** When no MCP server exists that you'd trust, write the tool yourself: a module in `src/kiri/tools/`. OAuth is shared plumbing (`kiri auth login <plugin>`), not something each plugin reinvents.

## Setup

```sh
cp kiri.example.toml kiri.toml
uv sync
uv run kiri
```

Three things are required: a provider api key, a Discord bot token, and your Discord user id as `owner_id`. Every key is documented in `kiri.example.toml`.

For the bot: create one in the [Discord developer portal](https://discord.com/developers/applications), you will need the **Message Content Intent**.

Scheduled jobs only fire while Kiri is running, so recommended to use systemd (or Docker!) I've provided a systemd service at `deploy/kiri.service` and a `Dockerfile` — add the CLIs you want Kiri to have to its apt-get layer.

## Extending Kiri

Kiri ships no app integrations, so "how do I add one" is the first question anyone asks. The answer depends on **who the capability is for**, and it is not a matter of taste:

| Who is it for? | What you write |
|---|---|
| Every Kiri owner, and a good MCP server exists | an entry in `mcp.json` |
| Every Kiri owner, and none exists you'd trust | a plugin (`src/kiri/tools/`) |
| Kiri's own harness (jobs, sessions, routing) | a plugin |
| You alone (your accounts, your commute) | a program on your `PATH` — the shell already drives it |
| People and agents beyond Kiri | an MCP server, then consume it |

A tool's schema rides in *every* request Kiri ever makes, whether or not it's used — so the bar for a first-party tool is "the median owner wants this," not "I want this." Knowing *how* to use something Kiri can already reach isn't a tool at all; that's a skill. `CLAUDE.md` has the reasoning behind each of these.

### Writing a plugin

A module under `src/kiri/tools/`, exporting a `SCHEMA` and an `async run(args)` that returns a string — then one `registry.add(...)` line in `tools/__init__.py`. MCP tools are wrapped into the same shape, so the registry can't tell them apart. `tools/web.py` is a complete example in 75 lines.

The `description` is a prompt, not a docstring: it is the only thing Kiri uses to decide whether to call you. Return a string even on failure (`"error: ..."`) — a plugin that raises kills the turn, one that returns an error lets the model read it and adapt.

If it needs OAuth, construct an `oauth.OAuth` at module scope and `kiri auth login <name>` picks it up; tokens land in `credentials.json` with everything else. Never hand-roll a token flow in a plugin, and never wrap a capability in MCP just to reach the auth code that already exists — if the rail doesn't cover your service's flow, widen the rail.

### Writing a skill

One `<name>/SKILL.md` in `~/.kiri/skills`, with `name` and `description` in the frontmatter:

```markdown
---
name: todoist-cli
description: Manage tasks and projects via the `td` CLI. Use when the owner mentions tasks, inbox, today, upcoming, projects, labels, or filters.
---

- `td auth token view` prints the token to stdout. Always capture it into a shell
  variable -- invoking it bare leaks the secret into the transcript.
- Don't `curl` an attachment url and read the file: a rejected image pins itself
  in context and breaks the session. Use `td attachment view <url>`.
```

Only the `description` stays in context. The body is read on demand, so it can be as long as it needs to be. Keep each frontmatter field on one line — a wrapped line is rejected at boot rather than silently truncated.

**What belongs in a skill is inversely proportional to how easily Kiri could rediscover it with the shell.** A digest of `--help` earns its place only by saving round-trips. What `--help` will never say — this flag leaks a secret, that fetch kills the session, these two commands both look right and one is wrong — is the actual payload. Write the scars first.

Run `reload` after editing one.

## Development

```sh
uv run pytest -q
```
