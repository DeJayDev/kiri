import platform
import socket
from datetime import datetime, timezone

from kiri import config
from kiri.engine import llm


def runtime_context():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return (
        f"Runtime: {now}, host {socket.gethostname()}, {platform.system()}. "
        f"Your long-term memory is flat files under {config.MEMORY_DIR}; "
        "read and update it with the shell (rg, cat, write)."
    )


class Session:
    def __init__(self, channel_id, base_system):
        self.channel_id = channel_id
        self.base_system = base_system
        self.messages = []
        self.summary = ""
        self.pinned = []
        self.last_input_tokens = 0

    def system(self):
        parts = [self.base_system, runtime_context()]
        if self.pinned:
            parts.append("Pinned by the user:\n" + "\n".join(self.pinned))
        if self.summary:
            parts.append("Summary of earlier conversation:\n" + self.summary)
        return "\n\n".join(parts)

    def append_user(self, text):
        self.messages.append({"role": "user", "content": text})

    def append_assistant(self, content):
        self.messages.append({"role": "assistant", "content": content})

    def append_tool_results(self, results):
        self.messages.append({"role": "user", "content": results})

    def record_usage(self, usage):
        self.last_input_tokens = usage.get("input_tokens", self.last_input_tokens)

    async def maybe_compact(self):
        if self.last_input_tokens < config.COMPACT_AT * config.MODEL_CONTEXT:
            return

        cut = self._safe_cut()
        if cut <= 0:
            return

        old, self.messages = self.messages[:cut], self.messages[cut:]
        self.summary = await self._summarize(old)

    def _safe_cut(self):
        # Keep the last KEEP_RECENT messages, then walk the boundary back to a
        # real user turn so the retained tail never starts with an orphan
        # tool_result (which must follow its assistant tool_use).
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
        data = await llm.complete(instruction, messages, None)
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
