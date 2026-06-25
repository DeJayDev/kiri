import asyncio

import discord

from ... import config
from ...engine import conversation
from . import output

_intents = discord.Intents.default()
_intents.message_content = True
_intents.dm_messages = True


class Kiri(discord.Client):
    def __init__(self, sessions, store, mcp_tools):
        super().__init__(intents=_intents)
        self.sessions = sessions
        self.store = store
        self.mcp_tools = mcp_tools
        self.tasks = {}

    async def on_message(self, message):
        if message.author.id == self.user.id:
            return
        if not isinstance(message.channel, discord.DMChannel):
            return
        if message.author.id != config.OWNER_ID:
            return

        channel_id = message.channel.id
        running = self.tasks.get(channel_id)
        if running and not running.done():
            running.cancel()  # any new message aborts the in-flight run

        text = message.content.strip()
        if text.lower() in {"stop", "cancel"}:
            await message.channel.send("stopped.")
            return

        self.tasks[channel_id] = asyncio.create_task(self._handle(message, text))

    async def _handle(self, message, text):
        channel = message.channel
        session = self.sessions.get(channel.id)
        slow = asyncio.create_task(self._slow_note(channel))
        try:
            async with channel.typing():
                reply = await conversation.run_turn(session, text, self.store, self.mcp_tools)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            await output.send(channel, f"error: {exc}")
            return
        finally:
            slow.cancel()
        await output.send(channel, reply)

    async def _slow_note(self, channel, delay=20):
        await asyncio.sleep(delay)
        await channel.send("working on it...")

    async def deliver(self, channel_id, text):
        channel = self.get_channel(channel_id) or await self.fetch_channel(channel_id)
        await output.send(channel, text)
