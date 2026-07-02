import asyncio

import discord

from kiri import config, stt, usage
from kiri.engine import conversation
from kiri.transports.discord import output

_intents = discord.Intents.default()
_intents.message_content = True
_intents.dm_messages = True


def _voice_attachment(message):
    # Voice messages carry the IS_VOICE_MESSAGE flag and exactly one audio
    # attachment; the flag alone is sufficient to identify them.
    if not message.flags.voice:
        return None
    return message.attachments[0]


class Kiri(discord.Client):
    def __init__(self, sessions, store, mcp_tools):
        super().__init__(intents=_intents)
        self.sessions = sessions
        self.store = store
        self.mcp_tools = mcp_tools
        self.tasks = {}
        self.pending = {}

    async def on_message(self, message):
        if message.author == self.user:
            return
        if not isinstance(message.channel, discord.DMChannel):
            return
        if message.author.id != config.OWNER_ID:
            return

        channel_id = message.channel.id
        running = self.tasks.get(channel_id)
        text = message.content.strip()

        if text.lower() in {"stop", "cancel"}:
            # Clear in place: the drain loop holds a reference to this list, so
            # popping the dict entry wouldn't stop queued turns from running.
            queue = self.pending.get(channel_id)
            if queue:
                queue.clear()
            if running and not running.done():
                running.cancel()
            await message.channel.send("stopped.")
            return

        voice = _voice_attachment(message)
        if running and not running.done():
            # A message during a run is a follow-up, not an interrupt; it runs
            # as its own turn once the current one finishes.
            self.pending.setdefault(channel_id, []).append((message, text, voice))
            return
        self.tasks[channel_id] = asyncio.create_task(self._drain(message, text, voice))

    async def _drain(self, message, text, voice):
        queue = self.pending.setdefault(message.channel.id, [])
        queue.append((message, text, voice))
        while queue:
            await self._handle(*queue.pop(0))

    async def _handle(self, message, text, voice):
        channel = message.channel
        session = self.sessions.get(channel.id)
        slow = asyncio.create_task(self._slow_note(channel))
        try:
            async with channel.typing():
                if voice:
                    text = await stt.transcribe(await voice.read())
                    if not text:
                        await output.send(
                            channel, "couldn't make out any speech in that voice message."
                        )
                        return
                    # Echo the transcription so the user can see what was understood.
                    await channel.send(f"heard: {text}")
                reply = await conversation.run_turn(
                    session, text, self.store, self.mcp_tools, on_usage=usage.record
                )
            self.sessions.save(session)
            await output.send(channel, reply)
        except asyncio.CancelledError:
            # Swallowed on purpose: cancel aborts this turn, not the drain loop,
            # so a follow-up sent mid-cancel still gets served. The half-finished
            # turn is discarded so its instruction never leaks into history.
            self.sessions.drop(channel.id)
            return
        except Exception as exc:
            await output.send(channel, f"error: {exc}")
            return
        finally:
            slow.cancel()

    async def _slow_note(self, channel, delay=20):
        await asyncio.sleep(delay)
        await channel.send("working on it...")

    async def deliver(self, channel_id, text):
        channel = self.get_channel(channel_id) or await self.fetch_channel(channel_id)
        await output.send(channel, text)

    async def notify_owner(self, text):
        user = self.get_user(config.OWNER_ID) or await self.fetch_user(config.OWNER_ID)
        channel = user.dm_channel or await user.create_dm()
        await output.send(channel, text)
