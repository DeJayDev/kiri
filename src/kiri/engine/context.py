import platform
import socket
from datetime import datetime, timezone

from kiri import config
from kiri.engine import llm


def environment():
    return (
        f"Host {socket.gethostname()}, {platform.system()}. "
        f"Your long-term memory is flat files under {config.MEMORY_DIR}; "
        "read and update it with the shell (rg, cat, write)."
    )


def _today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class Session:
    def __init__(self, channel_id, base_system):
        self.channel_id = channel_id
        self.base_system = base_system
        self.messages = []
        self.summary = ""
        self.pinned = []
        self.last_input_tokens = 0

    def system(self):
        # Ordered segments, stable first. A caching provider breakpoints the last
        # one, so nothing per-request may appear here.
        parts = [self.base_system, environment()]
        if self.pinned:
            parts.append("Pinned by the user:\n" + "\n".join(self.pinned))
        if self.summary:
            parts.append("Summary of earlier conversation:\n" + self.summary)
        return parts

    def append_user(self, text):
        self.messages.append({"role": "user", "content": f"{text}\n\nToday is {_today()} (UTC)."})

    def append_assistant(self, content):
        self.messages.append({"role": "assistant", "content": content})

    def append_tool_results(self, results):
        self.messages.append({"role": "user", "content": results})

    def seal_dangling_tools(self):
        # A restart can cut a turn between an assistant tool_use and its result; the
        # next request 400s on the unanswered tool_use. Fill each so resume replays
        # cleanly, the same shape the reload tool writes before it re-execs.
        if not self.messages:
            return
        last = self.messages[-1]
        if last["role"] != "assistant" or isinstance(last["content"], str):
            return
        ids = [b["id"] for b in last["content"] if b.get("type") == "tool_use"]
        if not ids:
            return
        self.append_tool_results(
            [{"type": "tool_result", "tool_use_id": i, "content": "interrupted by a restart"} for i in ids]
        )

    def record_usage(self, usage):
        # input_tokens is only the uncached remainder; on its own it reports a full
        # context as tiny and compaction never fires.
        total = (
            usage.get("input_tokens", 0)
            + usage.get("cache_creation_input_tokens", 0)
            + usage.get("cache_read_input_tokens", 0)
        )
        if total:
            self.last_input_tokens = total

    async def maybe_compact(self):
        if self.last_input_tokens < config.COMPACT_AT * config.MODEL_CONTEXT:
            return

        cut = self._safe_cut()
        if cut <= 0:
            return

        old, self.messages = self.messages[:cut], self.messages[cut:]
        self.summary = await self._summarize(old)

    def _safe_cut(self):
        # Walk back to a real user turn: the retained tail must not start on an
        # orphan tool_result, which has to follow its assistant tool_use.
        cut = len(self.messages) - config.KEEP_RECENT
        while cut > 0 and not _is_user_turn(self.messages[cut]):
            cut -= 1
        return cut

    async def _summarize(self, old):
        transcript = _render(old)
        prior = f"Existing summary:\n{self.summary}\n\n" if self.summary else ""
        instruction = (
            "Summarize the conversation below into a dense, factual brief that "
            "preserves decisions, open threads, and any facts needed to continue. "
            "No preamble, no commentary."
        )
        messages = [{"role": "user", "content": f"{prior}{instruction}\n\n{transcript}"}]
        # Deliberately not record_usage(): this call's input size is the
        # pre-compaction transcript, which would immediately re-trigger compaction.
        data = await llm.summarize(instruction, messages, model=config.SUMMARY_MODEL)
        return llm.text_of(data["content"])


def _is_user_turn(message):
    return message["role"] == "user" and isinstance(message["content"], str)


def _render(messages):
    lines = []
    for m in messages:
        content = m["content"]
        if isinstance(content, str):
            lines.append(f"{m['role']}: {content}")
            continue
        for block in content:
            kind = block.get("type")
            if kind == "text":
                lines.append(f"{m['role']}: {block['text']}")
            elif kind == "tool_use":
                lines.append(f"{m['role']} -> tool {block['name']}({block.get('input', {})})")
            elif kind == "tool_result":
                lines.append(f"tool_result: {block.get('content', '')}")
    return "\n".join(lines)
