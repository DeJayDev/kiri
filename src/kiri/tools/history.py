import json
from itertools import islice

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
            "query": {"type": "string", "description": "Only messages containing this text, case-insensitive."},
            "count": {"type": "integer", "description": "How many messages. Defaults to 20."},
            "skip": {"type": "integer", "description": "Skip this many of the newest first, to page back."},
        },
    },
}


def build(channel_id):
    async def history(args):
        query = (args.get("query") or "").lower()
        rows = (
            Transcript.select()
            .where(Transcript.channel_id == channel_id)
            # Rows are stored as JSON, so the query is matched in its JSON-escaped
            # form; the rendered check below drops hits on keys like "type" or "text".
            .where(Transcript.message.contains(json.dumps(query)[1:-1]))
            .order_by(Transcript.id.desc())
        )
        messages = (json.loads(row.message) for row in rows.iterator())
        matches = (m for m in messages if query in _render([m]).lower())
        skip = args.get("skip") or 0
        page = list(islice(matches, skip, skip + (args.get("count") or 20)))
        if page:
            return _render(page[::-1])
        if query:
            return f"no earlier messages contain {args['query']!r}"
        return "no earlier messages"

    return history
