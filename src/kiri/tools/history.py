import json

from kiri.db import Transcript
from kiri.engine.context import _render

SCHEMA = {
    "name": "history",
    "description": (
        "Read earlier messages of this DM that are no longer in your context: "
        "compacted away, cleared by /new, or from scheduled runs. Shows tool calls "
        "with trimmed results, oldest first."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "count": {"type": "integer", "description": "How many messages. Defaults to 20."},
            "skip": {"type": "integer", "description": "Skip this many of the newest first, to page back."},
        },
    },
}


def build(channel_id):
    async def history(args):
        rows = (
            Transcript.select()
            .where(Transcript.channel_id == channel_id)
            .order_by(Transcript.id.desc())
            .offset(args.get("skip") or 0)
            .limit(args.get("count") or 20)
        )
        messages = [json.loads(row.message) for row in reversed(list(rows))]
        return _render(messages) or "no earlier messages"

    return history
