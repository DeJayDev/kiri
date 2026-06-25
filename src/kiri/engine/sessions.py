from .context import Session


class SessionStore:
    # One rolling session per channel, held for the process lifetime.
    def __init__(self, base_prompt):
        self.base_prompt = base_prompt
        self._sessions = {}

    def get(self, channel_id):
        if channel_id not in self._sessions:
            self._sessions[channel_id] = Session(channel_id, self.base_prompt)
        return self._sessions[channel_id]
