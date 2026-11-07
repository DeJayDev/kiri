import json
import time

from kiri.db import Conversation, Transcript
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

    def flush(self):
        for session in self._sessions.values():
            self.save(session)

    def reset(self, channel_id):
        self.archive(channel_id, self.get(channel_id).messages)
        session = Session(channel_id, self.base_prompt)
        self._sessions[channel_id] = session
        self.save(session)

    def drop(self, channel_id):
        # Forget the in-memory session; the next get() reloads the last saved
        # state, discarding any half-finished turn.
        self._sessions.pop(channel_id, None)

    def note(self, channel_id, text):
        session = self.get(channel_id)
        session.note(text)
        row = Conversation.get_or_none(Conversation.channel_id == channel_id)
        if row is None:
            self.save(session)
            return
        # Appended to the stored list rather than saving the session: a live turn may
        # be mid tool call, and may have folded earlier notes into a message that is
        # not checkpointed yet.
        notes = json.dumps([*json.loads(row.notes), text])
        Conversation.update(notes=notes).where(Conversation.channel_id == channel_id).execute()

    def _load(self, channel_id):
        row = Conversation.get_or_none(Conversation.channel_id == channel_id)
        if row is None:
            return None
        session = Session(channel_id, self.base_prompt)
        session.messages = json.loads(row.messages)
        session.summary = row.summary
        session.last_input_tokens = row.last_input_tokens
        session.notes = json.loads(row.notes)
        return session

    def archive(self, channel_id, messages):
        now = time.time()
        rows = [{"channel_id": channel_id, "ts": now, "message": json.dumps(m)} for m in messages]
        if rows:
            Transcript.insert_many(rows).execute()

    def save(self, session):
        self.archive(session.channel_id, session.archived)
        session.archived = []
        Conversation.replace(
            channel_id=session.channel_id,
            messages=json.dumps(session.messages),
            summary=session.summary,
            last_input_tokens=session.last_input_tokens,
            notes=json.dumps(session.notes),
        ).execute()
