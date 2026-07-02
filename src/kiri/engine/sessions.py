import json

from kiri.db import Conversation
from kiri.engine.context import Session


class SessionStore:
    # One rolling session per channel, cached in memory and persisted to the
    # harness store so conversations survive a restart.
    def __init__(self, base_prompt):
        self.base_prompt = base_prompt
        self._sessions = {}

    def get(self, channel_id):
        if channel_id in self._sessions:
            return self._sessions[channel_id]
        session = self._load(channel_id) or Session(channel_id, self.base_prompt)
        self._sessions[channel_id] = session
        return session

    def drop(self, channel_id):
        # Forget the in-memory session; the next get() reloads the last saved
        # state, discarding any half-finished turn.
        self._sessions.pop(channel_id, None)

    def _load(self, channel_id):
        row = Conversation.get_or_none(Conversation.channel_id == channel_id)
        if row is None:
            return None
        session = Session(channel_id, self.base_prompt)
        session.messages = json.loads(row.messages)
        session.summary = row.summary
        session.pinned = json.loads(row.pinned)
        session.last_input_tokens = row.last_input_tokens
        return session

    def save(self, session):
        Conversation.replace(
            channel_id=session.channel_id,
            messages=json.dumps(session.messages),
            summary=session.summary,
            pinned=json.dumps(session.pinned),
            last_input_tokens=session.last_input_tokens,
        ).execute()
