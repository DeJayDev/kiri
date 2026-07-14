# Kiri

Keep Kiri a minimal, un-opinionated personal agent that runs on the owner's
machine, talks over Discord DM, and does exactly what it is asked with the tools
it is given. Do not turn it into a coding agent.

Treat this file as rules, not notes. Every line is something you can be held to.

## Hard constraints (never break)

- **Never edit this file to fit code you just wrote.** The rules are the owner's.
  If one blocks you, say so and stop — don't rewrite it or add a clause that makes
  your change legal. Changes here are their own task, asked for on purpose.
- **No `anthropic` SDK.** Keep the model loop hand-rolled over `httpx`. The `mcp`
  SDK is allowed; it is how MCP servers are loaded.
- **No Anthropic server-side tools** such as web search or fetch. Keep web search
  and fetch in Kiri's own code against Exa.
- **Fail loud, never guess.** Surface the real error. Retrying a 429 or a dropped
  socket is not a guess; papering over a 400, a bad key, or a malformed response
  is. Carry the status; never diagnose by string-matching an error message.
- **Never commit secrets.** `kiri.toml`, `.env`, `*.db`, `mcp.json`, and
  `credentials.json` are gitignored because they hold real credentials. Do not
  read or stage them.
- **Preserve the storage split.** Keep harness state such as sessions, jobs, and
  usage in sqlite at `DB_PATH`; the agent never reads it. Keep agent memory in
  flat files under `MEMORY_DIR`, where the model greps it with the shell; never
  put agent memory in sqlite. Keep OAuth tokens in `credentials.json` with mode
  0600, never sqlite, so recovery from a bad token remains "delete the file."
  Keep skills in flat files under `SKILLS_DIR`, written by the **owner**, not the
  model. That authorship difference is what lets skill descriptions ride in the
  prompt prefix; memory cannot.
- **Preserve the message and engine boundary.** Use Anthropic content blocks
  (`tool_use`, `tool_result`, `text`) as the internal message shape everywhere.
  Keep the model loop in `engine/` provider-agnostic and free of outside I/O;
  isolate provider I/O in the provider adapters, and inject providers and the
  usage sink at boot.

## The model is the feature. The harness is plumbing.

Hand a capable model a shell and get out of the way. A model that adapts beats a
harness that guessed. Before adding code, determine whether the model can already
do the work:

- For the time, let it run `date`. Put only the **date** in context, never a
  clock. Do not add a clock.
- For a file's contents, command output, or installed software, let it use the
  shell.
- For a missing capability, apply the prompt-commons rules below.
- Let the model decide how long something should take or how much of something to
  do. If it does not specify a value, choose one and hardcode it.

Keep the agent loop as `while True`. Do not cap, budget, or police it. If it
spins, fix the prompt; `stop` is the escape hatch.

## The prompt prefix is a commons

Treat every tool schema as a recurring cost charged to every owner. Schemas ride
in every request at the front of the cache prefix (`tools` → `system` →
`messages`), even when they are never called. They consume context, compete for
the model's attention, and changing one invalidates the whole prefix. The shell
is the only place where a new capability costs zero marginal schema: one tool,
unlimited capabilities.

Never ask whether a capability would be nicer as a tool; everything would. Ask
who it is for and whether that audience justifies billing every owner on every
request.

### Put each capability at the boundary its audience earns

1. **For Kiri's harness:** write a plugin. Jobs DB access, the session, channel
   routing, and the registry are in-process state that no subprocess can honestly
   reach; there is no other option. `schedule_job` and `reload` belong here.
2. **For every Kiri owner:** make it first-party only when the median owner would
   want it often. Connect an existing MCP server if one exists, is maintained,
   and is trustworthy with everything a personal agent holding a shell can reach.
   Otherwise write a plugin: a module under `src/kiri/tools/` with a `SCHEMA` and
   an `async run(args)`.
3. **For one owner:** put a program on that owner's `PATH`. Personal addresses,
   accounts, and habits do not belong in every other owner's schema block. Let
   the existing shell drive it.
4. **For people and agents beyond Kiri:** author an MCP server, then consume it
   from Kiri like any other MCP server.

Writing an MCP server whose only client is Kiri is never right: that's a network
protocol between two functions you own both ends of. Native and MCP tools are
already identical to the model once registered. MCP buys someone else's
maintenance; when that someone is you, it buys nothing.

Apply one test to every proposed schema: **would the median Kiri owner want this
in the tool block of every request they ever make?**

### Use skills for procedures, never capabilities

A skill is a procedure and a trigger for something that already executes: a CLI,
a plugin, an MCP server, or the bare shell. Do not use a skill to pretend a
capability exists.

Store exactly one `<name>/SKILL.md` per skill under `SKILLS_DIR`, with `name` and
`description` in its frontmatter. Index only the descriptions into the prompt at
boot. Never load skill bodies automatically; the model must `cat` the one it
needs, and an owner may force one with `/<name>`. Keep the mechanism to files, an
index, and the shell.

Make a skill earn its place in inverse proportion to how easily the shell could
rediscover it:

- Include re-derivable `--help` material only when a quick reference saves the
  model many round-trips. That is cheap, but it is not the point.
- Write the scars first: the flag that leaks a secret into the transcript, the
  fetch that pins a broken image in context and kills the session, or the two
  commands that look right when only one is. That is what the shell will never
  teach safely.

Keep skills and memory separate even though both are flat files:

- **Memory is model-written and churns at runtime.** Keep it out of the prompt
  prefix. Never index it in `Session.system()`; doing so would bust the cache on
  every note the agent writes. Leave memory grep-discovered by design.
- **Skills are owner-written and change rarely.** Their one-line descriptions
  may sit in the prompt prefix because they change only when the owner edits
  them. An edit takes effect through `reload`, which re-execs Kiri.

Do not add a second tier of unindexed skills to avoid the index line. A dozen
descriptions cost only a few hundred cached tokens. Split the mechanism only if
the count actually explodes.

### Reuse the OAuth rail for first-party plugins

Use `oauth.OAuth` for authorization-code + PKCE services that issue a `client_id`
up front, such as Google, Notion, or Spotify. Use `mcp_auth` for MCP servers that
register a client dynamically under RFC 7591; almost nothing outside MCP does
that. Construct an `oauth.OAuth` at module scope so `kiri auth login <name>` and
`kiri auth status` discover it, and keep its tokens in `credentials.json` with
the other credentials.

- **Never hand-roll a token flow inside a plugin.** Extend the rail.
- **Never wrap a capability in MCP just to reach existing auth code.** The rail
  is generic specifically to prevent that.
- Treat an unsupported flow as a gap in the rail, not a wall. Widen the rail when
  the first plugin needs that flow, never before.

### Keep the prefix cacheable

Preserve prompt caching as a prefix match: one changed byte invalidates
everything after it. Preserve render order as `tools` → `system` → `messages`.

- Keep per-request data out of `Session.system()`. A `datetime.now()` there once
  made the cache unhittable.
- Call `skills.index()` **once at boot** and fold its result into the base prompt.
  Do not move it into `Session.system()` to "pick up edits live"; that rescans
  `SKILLS_DIR` every request and puts a filesystem read in the cache prefix.
  `reload` re-execs Kiri; that is how an edited skill takes effect.
- Treat `input_tokens` as the **uncached remainder**, not the full context. True
  context is `input + cache_read + cache_write`; `record_usage` must sum all
  three or compaction never fires.
- Normalize provider usage so `input_tokens` means uncached input everywhere.

## Don't add what you don't need

- **No config knob nobody sets.** If the wrong value costs cents and the right
  value is obvious, hardcode it. Cache TTL, retry backoff, and shell timeout stay
  literals. A knob that exists only so the code can read it back is not a
  feature.
- **No named constant for a value used once.** Inline it.
- **No abstraction with one implementation.** Add a seam only when something has
  a lifecycle the current shape cannot hold. "It might be useful later" does not
  earn one.
- **No scaffolding for the model's benefit.** Do not add forced summaries after
  N tool calls, forced progress notes, or context the model could fetch itself.
- **Use the library the way it expects.** Peewee has migrations; do not hand-roll
  reflection over its models. Reach for the boring documented path first.
- Deleting beats adding. Fix the root cause, not the symptom the report named.

## Comments and text the model reads

- Put comments above the line, never trailing.
- **In code, comment only an invariant that silently breaks if violated.** Do not
  restate the line, justify a choice, address a reviewer, or summarize a diff. If
  you cannot name what breaks without the comment, delete it. Commentary is the
  default failure; write less than feels right.
- **In example configs** (`kiri.example.toml`, `mcp.example.json`), invert the
  code rule. Explain values whose names are insufficient: that `int8` is the fast
  CPU default, that the choice is `cpu | cuda`, or which environment variable
  overrides a value. Those files are the only place that setup knowledge is
  written down; do not strip it as noise.
- **Keep extension recipes in `README.md`; never duplicate them here.** This file
  names a shape only as far as a rule needs to be actionable (`SCHEMA` plus
  `async run(args)`; `name` plus `description` frontmatter). Working examples,
  module skeletons, and the OAuth walkthrough belong in `README.md`. When
  extension mechanics change, update the corresponding recipe in `README.md` in
  the same change. Edit this file only when the owner separately asks to change
  its rules.
- **Treat text the model reads as a prompt.** For tool descriptions, tool error
  strings, and a skill's `description`, state the fact and the single action that
  follows in one or two sentences. Do not lecture, apologize, or give instructions
  for a situation the model cannot act on. A skill's `description` is always
  loaded only so the model knows when to open the file; put nothing else there.
- **Invert the code-comment rule in a skill body.** Record what the shell cannot
  teach: the secret-leaking flag, the session-killing fetch, and the deceptively
  similar commands where one is wrong. Those are the payload, not commentary.

## Style

- Use early returns, top-to-bottom control flow, small functions, and no
  docstrings.
- Produce plain-text output. No emojis.
- Resolve config through `config._get` with `env > TOML > default`. There is no
  `max_tokens` setting; it was deliberately removed. Do not add one.
- Do not use `pytest-asyncio`; call `asyncio.run` in tests.

## Commands

```sh
uv sync                          # core deps
uv sync --extra stt              # + on-device voice transcription (faster-whisper)
uv run pytest -q                 # tests
uv run kiri                      # boot (transport from config; KIRI_TRANSPORT=terminal for a repl)
uv run kiri usage                # token tally + cache hit rate
uv run kiri auth status          # provider + plugin credentials
uv run kiri auth login xai       # device-code oauth (a model provider)
uv run kiri auth login <plugin>  # browser oauth (a plugin's oauth.OAuth)
uv run kiri mcp                  # remote mcp servers + auth state
uv run kiri mcp <server>         # authorize one (browser)
```
