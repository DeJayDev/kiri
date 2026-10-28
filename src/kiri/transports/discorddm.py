import asyncio
import io
import os
from contextlib import asynccontextmanager

import discord

from kiri import config
from kiri.transports.base import Inbound, Transport

_LIMIT = 2000
_FENCE = "```"

_intents = discord.Intents.default()
_intents.message_content = True
_intents.dm_messages = True


def _voice_attachment(message):
    if not message.flags.voice or not message.attachments:
        return None
    return message.attachments[0]


async def _images(message):
    out = []
    for attachment in message.attachments:
        if (attachment.content_type or "").startswith("image/"):
            out.append((attachment.content_type, await attachment.read()))
    return out


async def _files(message, voice):
    # Everything that isn't an image or the voice note, saved where the shell can
    # read it. Discord turns a long paste into message.txt, which lands here too.
    out = []
    for attachment in message.attachments:
        if attachment is voice or (attachment.content_type or "").startswith("image/"):
            continue
        folder = os.path.join(config.INBOX_DIR, str(message.id))
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, os.path.basename(attachment.filename))
        await attachment.save(path)
        out.append(path)
    return out


def _segments(text):
    # Paragraphs, except a fenced code block stays whole even across blank lines.
    segments, current, fenced = [], [], False
    for line in text.split("\n"):
        if line.strip().startswith(_FENCE):
            fenced = not fenced
        if not line.strip() and not fenced:
            if current:
                segments.append("\n".join(current))
                current = []
            continue
        current.append(line)
    if current:
        segments.append("\n".join(current))
    return segments


def _fit(segment):
    # A segment over the limit is cut between lines; a cut inside a code block
    # closes the fence and reopens it with the same opener, so both halves render.
    if len(segment) <= _LIMIT:
        return [segment]
    room = _LIMIT - 20
    lines = []
    for line in segment.split("\n"):
        if not line:
            lines.append(line)
            continue
        lines.extend(line[i : i + room] for i in range(0, len(line), room))

    pieces, current, fence = [], [], None
    for line in lines:
        closing = f"\n{_FENCE}" if fence else ""
        if current and len("\n".join([*current, line])) + len(closing) > _LIMIT:
            pieces.append("\n".join(current) + closing)
            current = [fence] if fence else []
        current.append(line)
        if line.strip().startswith(_FENCE):
            fence = None if fence else line.strip()
    pieces.append("\n".join(current))
    return pieces


def _split(text):
    chunks, current = [], ""
    for segment in _segments(text):
        for piece in _fit(segment):
            joined = f"{current}\n\n{piece}" if current else piece
            if len(joined) <= _LIMIT:
                current = joined
                continue
            chunks.append(current)
            current = piece
    if current:
        chunks.append(current)
    return chunks


class _OtherModal(discord.ui.Modal):
    def __init__(self, view, question):
        super().__init__(title="Answer")
        self._view = view
        # Discord rejects the whole modal if a text input label runs past 45
        # characters.
        self._answer = discord.ui.TextInput(
            label=question[:45],
            style=discord.TextStyle.paragraph,
        )
        self.add_item(self._answer)

    async def on_submit(self, interaction):
        self._view.answer = str(self._answer)
        await interaction.response.edit_message(view=None)
        self._view.stop()


class _AnswerView(discord.ui.View):
    def __init__(self, question, options, multi_select):
        # No answer within the hour and the tool reports the timeout, rather than
        # holding the turn open forever.
        super().__init__(timeout=3600)
        self.answer = None
        # Discord caps a select option's label and description at 100 characters
        # each.
        select = discord.ui.Select(
            placeholder="Pick an answer",
            max_values=len(options) if multi_select else 1,
            options=[
                discord.SelectOption(
                    label=option["label"][:100],
                    description=(option.get("description") or "")[:100] or None,
                )
                for option in options
            ],
        )
        select.callback = self._pick(select)
        self.add_item(select)

        other = discord.ui.Button(label="Something else", style=discord.ButtonStyle.secondary)
        other.callback = self._other(question)
        self.add_item(other)

    def _pick(self, select):
        async def callback(interaction):
            self.answer = ", ".join(select.values)
            await interaction.response.edit_message(view=None)
            self.stop()

        return callback

    def _other(self, question):
        async def callback(interaction):
            await interaction.response.send_modal(_OtherModal(self, question))

        return callback


class _Live:
    def __init__(self, transport, channel_id):
        self._transport = transport
        self._channel_id = channel_id
        self._text = ""
        self._message = None
        self._closed = asyncio.Event()
        self._task = None

    def feed(self, delta):
        self._text += delta
        if self._task is None:
            self._task = asyncio.create_task(self._follow())

    async def _follow(self):
        # Discord rate-limits edits, so the preview catches up once a second
        # instead of on every delta.
        shown = ""
        while True:
            try:
                await asyncio.wait_for(self._closed.wait(), 1)
                return
            except TimeoutError:
                pass
            preview = self._text[:_LIMIT].strip()
            if preview and preview != shown:
                await self._show(preview)
                shown = preview

    async def _show(self, text):
        if self._message is None:
            channel = await self._transport._channel(self._channel_id)
            self._message = await channel.send(text)
            return
        await self._message.edit(content=text)

    async def close(self, final):
        if self._task is None:
            return False
        self._closed.set()
        await self._task
        if self._message is None:
            return False
        if final and len(final) <= _LIMIT:
            await self._message.edit(content=final)
            return True
        # Too long for one message, or the turn died: the normal send path takes
        # over, so the preview must not linger as a second copy.
        await self._message.delete()
        return False


class _Client(discord.Client):
    def __init__(self, transport):
        super().__init__(intents=_intents)
        self.transport = transport

    async def on_message(self, message):
        if message.author == self.user:
            return
        if not isinstance(message.channel, discord.DMChannel):
            return
        if message.author.id != config.OWNER_ID:
            return

        voice = _voice_attachment(message)
        audio = await voice.read() if voice else None
        await self.transport._on_message(
            Inbound(
                channel_id=message.channel.id,
                text=message.content.strip(),
                audio=audio,
                images=await _images(message) or None,
                quote=await self._quote(message),
                files=await _files(message, voice) or None,
            )
        )

    async def _quote(self, message):
        if message.reference is None or message.reference.message_id is None:
            return None
        try:
            quoted = await message.channel.fetch_message(message.reference.message_id)
        except discord.NotFound:
            return "In reply to a message that has since been deleted."

        body = [quoted.content] if quoted.content else []
        for attachment in quoted.attachments:
            if (attachment.content_type or "").startswith("text/"):
                body.append((await attachment.read()).decode("utf-8", "replace"))
            else:
                body.append(f"[attachment: {attachment.filename}]")
        lines = "\n".join(f"> {line}" for line in "\n".join(body).splitlines())

        if quoted.author == self.user:
            return f"In reply to your message:\n{lines}"
        return f"In reply to my earlier message:\n{lines}"


class DiscordDM(Transport):
    name = "discord"

    def __init__(self):
        self._client = _Client(self)
        self._on_message = None

    @classmethod
    def missing(cls):
        gaps = []
        if not config.DISCORD_BOT_TOKEN:
            gaps.append("discord token")
        if not config.OWNER_ID:
            gaps.append("discord owner_id")
        return ", ".join(gaps) or None

    async def run(self, on_message):
        self._on_message = on_message
        await self._client.start(config.DISCORD_BOT_TOKEN)

    async def ready(self):
        await self._client.wait_until_ready()

    async def _channel(self, channel_id) -> discord.DMChannel:
        channel = self._client.get_channel(channel_id) or await self._client.fetch_channel(
            channel_id
        )
        # A guild id here means a stored job points somewhere it shouldn't.
        if not isinstance(channel, discord.DMChannel):
            raise RuntimeError(
                f"discord: refusing to send to channel {channel_id} -- "
                f"{type(channel).__name__}, not a DM"
            )
        return channel

    async def send(self, channel_id, text):
        await self._write(await self._channel(channel_id), text)

    def live(self, channel_id):
        return _Live(self, channel_id)

    async def ask(self, channel_id, question, options, multi_select):
        channel = await self._channel(channel_id)
        view = _AnswerView(question, options, multi_select)
        await channel.send(question[:_LIMIT], view=view)
        if await view.wait():
            return "error: the owner did not answer within an hour"
        return view.answer

    async def _write(self, channel, text):
        chunks = _split(text or "") or ["(no output)"]
        if len(chunks) <= 4:
            for chunk in chunks:
                await channel.send(chunk)
            return
        buffer = io.BytesIO(text.encode("utf-8"))
        await channel.send("reply too long, attached.", file=discord.File(buffer, "reply.md"))

    async def send_file(self, channel_id, path):
        # Returns an error the model can act on (413: too large to upload), or None.
        channel = await self._channel(channel_id)
        try:
            await channel.send(file=discord.File(path))
        except discord.HTTPException as exc:
            return f"error: discord {exc.status}: {exc.text}"
        return None

    @asynccontextmanager
    async def typing(self, channel_id):
        channel = await self._channel(channel_id)
        async with channel.typing():
            yield

    async def owner_channel(self):
        user = self._client.get_user(config.OWNER_ID) or await self._client.fetch_user(
            config.OWNER_ID
        )
        channel = user.dm_channel or await user.create_dm()
        return channel.id

    async def notify_owner(self, text):
        await self._write(await self._channel(await self.owner_channel()), text)
