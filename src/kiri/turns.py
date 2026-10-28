import asyncio
import re

from kiri import resume, spans, stt
from kiri.auth.login import login
from kiri.engine import conversation
from kiri.engine.providers.base import AuthRequired
from kiri.scheduling import events
from kiri.skills import catalog
from kiri.tools import ask, reload
from kiri.tools.reload import Restart

_SLASH = re.compile(r"^/([a-z0-9][a-z0-9-]*)(?:[:\s]+(.*))?$", re.DOTALL)


def _expand_skill(text):
    # A /<name> invocation force-loads the skill body into this turn -- the model
    # reads the procedure instead of choosing whether to. Returns (message, error);
    # a matched name with no skill is the owner's typo, so fail loud.
    match = _SLASH.match(text.strip())
    if not match:
        return text, None

    name, rest = match.group(1), (match.group(2) or "").strip()
    body = catalog.load(name)
    if body is None:
        have = ", ".join(catalog.names()) or "none"
        return text, f"no skill '{name}'. have: {have}."

    message = f"The owner invoked the /{name} skill. Follow it now.\n\n{body}"
    if rest:
        message += f"\n\nTheir message: {rest}"
    return message, None


def _with_quote(inbound, text):
    if not inbound.quote:
        return text
    return f"{inbound.quote}\n\n{text}"


def _with_files(inbound, text):
    if not inbound.files:
        return text
    listed = "\n".join(f"Attached file: {path}" for path in inbound.files)
    return f"{text}\n\n{listed}".strip()


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

    def active_channel(self):
        for channel, task in self.tasks.items():
            if not task.done():
                return channel
        return None

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
        command = inbound.text.strip().lower()
        if command == "/new":
            self.sessions.reset(channel)
            await self.transport.send(channel, "fresh session.")
            return
        if command.startswith("/bg") and command[3:4].isspace():
            events.put(inbound.text.strip()[3:].strip())
            await self.transport.send(channel, "started in the background.")
            return

        session = self.sessions.get(channel)
        if command == "/retry" and not session.unanswered():
            await self.transport.send(channel, "nothing to retry.")
            return

        resume.begin(channel)
        slow = asyncio.create_task(self._slow_note(channel))
        try:
            async with self.transport.typing(channel):
                # /retry resumes from the last checkpoint, which already holds the
                # owner's message, exactly like a reload resume.
                text, images = None, None
                if command != "/retry":
                    text = await self._text(inbound)
                    if text is None:
                        return
                    images = inbound.images

                try:
                    async with spans.timed("turn", self.transport.name):
                        reply = await self._turn(session, text, images)
                except AuthRequired as exc:
                    slow.cancel()  # a login prompt under a heartbeat reads as a hang
                    await self.reauth(channel, exc.provider)
                    # Resume, don't replay: the failed request never appended a
                    # response, so the session still ends on a clean boundary and
                    # the mid-turn checkpoints stay intact. Replaying the original
                    # text would re-append it on top of them.
                    reply = await self._turn(session, None)

            self.sessions.save(session)
            if reply is not None:
                await self.transport.send(channel, reply)
        except Restart:
            self.sessions.save(session)
            resume.mark(channel)
            slow.cancel()
            try:
                reload.restart()  # replaces the process; nothing below runs
            except OSError as exc:
                resume.clear()
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
            await self.transport.send(channel, f"error: {exc}\nsend /retry to pick up from the last checkpoint.")
            return
        finally:
            slow.cancel()
            resume.end()

    async def _text(self, inbound):
        # The owner's message as the model should read it, or None once the owner
        # has been told why there is nothing to run.
        channel = inbound.channel_id
        text = inbound.text
        if inbound.audio:
            text = await stt.transcribe(inbound.audio)
            if not text:
                await self.transport.send(channel, "no speech in that.")
                return None
            await self.transport.send(channel, f"heard: {text}")

        text, err = _expand_skill(text)
        if err:
            await self.transport.send(channel, err)
            return None
        return _with_files(inbound, _with_quote(inbound, text))

    async def _turn(self, session, text, images=None):
        async def nudges():
            return await self._drain_nudges(session.channel_id)

        async def persist():
            self.sessions.save(session)

        return await conversation.run_turn(
            session, text, self.store, self.mcp_tools, self.transport, images, nudges, persist
        )

    async def _drain_nudges(self, channel):
        # Messages the owner sent while this turn was running. on_message left them
        # in the same queue _drain watches; draining them here folds them into the
        # live turn, and anything that lands after the turn's last step falls back
        # to _drain as a fresh turn.
        queue = self.pending.get(channel)
        if not queue:
            return "", None
        inbounds, queue[:] = queue[:], []
        texts, images = [], []
        for inbound in inbounds:
            text = inbound.text
            if inbound.audio:
                text = await stt.transcribe(inbound.audio)
            if inbound.images:
                images.extend(inbound.images)
            text = _with_files(inbound, _with_quote(inbound, text))
            if text:
                texts.append(text)
        return "\n\n".join(texts), images or None

    async def _slow_note(self, channel):
        minutes = 1
        await asyncio.sleep(60)
        while True:
            question = ask.waiting.get(channel)
            if question:
                await self.transport.send(channel, f"waiting on your answer: {question}")
            else:
                await self.transport.send(channel, f"still working ({minutes}m).")
            await asyncio.sleep(300)
            minutes += 5

    async def reauth(self, channel, provider):
        async def say(text):
            await self.transport.send(channel, text)

        await login(provider, say)
