import asyncio
import sys
from contextlib import asynccontextmanager

from kiri.transports.base import Inbound, Transport

_CHANNEL = 0


class Terminal(Transport):
    name = "terminal"

    @classmethod
    def missing(cls):
        return None

    async def run(self, on_message):
        print("kiri terminal. ctrl-d to quit, 'stop' to cancel a running turn.")
        while True:
            try:
                line = await asyncio.to_thread(input, "\n> ")
            except (EOFError, KeyboardInterrupt):
                print()
                return

            if not line.strip():
                continue

            task = await on_message(Inbound(channel_id=_CHANNEL, text=line))
            # One person, one prompt: wait rather than race the next prompt.
            if task:
                await task

    async def send(self, channel_id, text):
        print(text or "(no output)", flush=True)

    @asynccontextmanager
    async def typing(self, channel_id):
        yield

    async def notify_owner(self, text):
        print(text, file=sys.stderr, flush=True)
