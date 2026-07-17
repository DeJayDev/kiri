import asyncio

from kiri import stt
from kiri.auth.login import login
from kiri.engine import conversation
from kiri.engine.providers.base import AuthRequired
from kiri.tools import reload
from kiri.tools.reload import Restart


class Dispatcher:
    def __init__(self, transport, sessions, store, mcp_tools):
        self.transport = transport
        self.sessions = sessions
        self.store = store
        self.mcp_tools = mcp_tools
        self.tasks = {}
        self.pending = {}
        self.stopped = set()

    async def on_message(self, inbound):
        channel = inbound.channel_id
        running = self.tasks.get(channel)

        if inbound.text.strip().lower() in {"stop", "cancel"}:
            if not running or running.done():
                await self.transport.send(channel, "nothing running.")
                return None

            # Clear in place: the drain loop holds a reference to this list, so
            # popping the dict entry wouldn't stop queued turns from running.
            queue = self.pending.get(channel)
            if queue:
                queue.clear()
            self.stopped.add(channel)
            running.cancel()
            await self.transport.send(channel, "stopped.")
            return None

        # Enqueued here and nowhere else. If _drain also appended, a second message
        # arriving before the drain task's first step would land in the queue ahead
        # of the first, and get answered first.
        self.pending.setdefault(channel, []).append(inbound)
        if running and not running.done():
            return None

        task = asyncio.create_task(self._drain(channel))
        self.tasks[channel] = task
        return task

    async def _drain(self, channel):
        queue = self.pending.setdefault(channel, [])
        try:
            while queue:
                await self._handle(queue.pop(0))
        finally:
            # No await between the loop's last check and here, so on_message can't
            # slip a message into the queue we're about to drop.
            self.pending.pop(channel, None)
            self.tasks.pop(channel, None)
            self.stopped.discard(channel)

    async def _handle(self, inbound):
        channel = inbound.channel_id
        slow = asyncio.create_task(self._slow_note(channel))
        try:
            async with self.transport.typing(channel):
                text = inbound.text
                if inbound.audio:
                    text = await stt.transcribe(inbound.audio)
                    if not text:
                        await self.transport.send(channel, "no speech in that.")
                        return
                    await self.transport.send(channel, f"heard: {text}")

                try:
                    session = self.sessions.get(channel)
                    reply = await self._turn(session, text)
                except AuthRequired as exc:
                    # Roll back first: the half-turn ends on a tool_use with no
                    # result, which the replay would 400 on.
                    self.sessions.drop(channel)
                    slow.cancel()  # a login prompt under a heartbeat reads as a hang
                    await self.reauth(channel, exc.provider)
                    session = self.sessions.get(channel)
                    reply = await self._turn(session, text)

            self.sessions.save(session)
            await self.transport.send(channel, reply)
        except Restart:
            # The turn ends on a tool_use with no result, so it must not be saved --
            # the next boot would load it and 400 on every request.
            self.sessions.drop(channel)
            slow.cancel()
            await self.transport.send(channel, "reloading.")
            try:
                reload.restart()  # replaces the process; nothing below runs
            except OSError as exc:
                await self.transport.send(channel, f"error: reload failed, still running ({exc})")
            return
        except asyncio.CancelledError:
            self.sessions.drop(channel)
            if channel not in self.stopped:
                # Not the owner -- this is shutdown cancelling us. Swallowing it here
                # would keep draining queued turns while the loop tries to close.
                raise

            # The owner said stop. Swallowed on purpose: it kills this turn, not the
            # drain loop, so a follow-up sent mid-cancel still gets served.
            self.stopped.discard(channel)
            current = asyncio.current_task()
            if current:
                current.uncancel()
            return
        except Exception as exc:
            # Same rollback: a dangling tool_use with no tool_result 400s forever.
            self.sessions.drop(channel)
            await self.transport.send(channel, f"error: {exc}")
            return
        finally:
            slow.cancel()

    async def _turn(self, session, text):
        return await conversation.run_turn(
            session, text, self.store, self.mcp_tools, self.transport
        )

    async def _slow_note(self, channel):
        minutes = 1
        await asyncio.sleep(60)
        while True:
            await self.transport.send(channel, f"still working ({minutes}m).")
            await asyncio.sleep(300)
            minutes += 5

    async def reauth(self, channel, provider):
        async def say(text):
            await self.transport.send(channel, text)

        await login(provider, say)
