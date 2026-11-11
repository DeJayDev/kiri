import io
import os
from contextlib import asynccontextmanager

import discord
from discord import app_commands

from kiri import config
from kiri.engine.providers.base import viewable
from kiri.skills import catalog
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


def _inline(attachment):
    return viewable(attachment.content_type or "", attachment.size)


async def _images(message):
    out = []
    for attachment in message.attachments:
        if _inline(attachment):
            out.append((attachment.content_type, await attachment.read()))
    return out


async def _files(message, voice):
    # Everything that isn't the voice note or an image the model can view inline,
    # saved where the shell can read it. Discord turns a long paste into
    # message.txt, which lands here too.
    out = []
    for attachment in message.attachments:
        if attachment is voice or _inline(attachment):
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


def _blockquote(text):
    return "\n".join(f"> {line}" for line in text.splitlines())


async def _skill_names(interaction, current):
    # Discord shows at most 25 suggestions and cuts a label at 100 characters.
    return [
        app_commands.Choice(name=f"{name}: {text}"[:100], value=name)
        for name, text in catalog.descriptions().items()
        if current.lower() in name
    ][:25]


def _slash(transport, command, description, argument):
    async def invoke(interaction, text):
        if interaction.user.id != config.OWNER_ID:
            return
        # Discord shows "the application did not respond" unless the interaction is
        # answered within 3 seconds. The deferred reply stays as "thinking..." until
        # it is deleted.
        await interaction.response.defer(ephemeral=True)
        await transport._on_message(Inbound(channel_id=await transport.owner_channel(), text=text))
        await interaction.delete_original_response()

    async def bare(interaction: discord.Interaction):
        await invoke(interaction, f"/{command}")

    async def prompt(interaction: discord.Interaction, prompt: str):
        await invoke(interaction, f"/{command} {prompt}")

    async def skill(interaction: discord.Interaction, name: str, message: str = ""):
        await invoke(interaction, f"/{name} {message}".strip())

    built = app_commands.Command(
        name=command,
        description=description,
        callback={None: bare, "prompt": prompt, "skill": skill}[argument],
        allowed_contexts=app_commands.AppCommandContext(dm_channel=True),
    )
    if argument == "skill":
        built.autocomplete("name")(_skill_names)
    return built


class _Client(discord.Client):
    def __init__(self, transport):
        super().__init__(intents=_intents)
        self.transport = transport
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        for command, description, argument in self.transport._commands:
            self.tree.add_command(_slash(self.transport, command, description, argument))
        await self.tree.sync()

    def _from_owner(self, message):
        return isinstance(message.channel, discord.DMChannel) and message.author.id == config.OWNER_ID

    async def on_message_edit(self, before, after):
        # Discord also fires this when it attaches a link preview, with the text unchanged.
        if before.content == after.content or not self._from_owner(after):
            return
        await self.transport._on_message(
            Inbound(
                channel_id=after.channel.id,
                text=after.content.strip(),
                quote=f"This edits my earlier message, which read:\n{_blockquote(before.content)}",
            )
        )

    async def on_message(self, message):
        if not self._from_owner(message):
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
        lines = _blockquote("\n".join(body))

        if quoted.author == self.user:
            return f"In reply to your message:\n{lines}"
        return f"In reply to my earlier message:\n{lines}"


class DiscordDM(Transport):
    name = "discord"
    style = (
        "You are talking over a Discord DM. Discord renders a subset of markdown with no "
        "tables, so lay out tabular data as a list or a code block."
    )

    def __init__(self):
        self._client = _Client(self)
        self._on_message = None
        self._commands = []

    @classmethod
    def missing(cls):
        gaps = []
        if not config.DISCORD_BOT_TOKEN:
            gaps.append("discord token")
        if not config.OWNER_ID:
            gaps.append("discord owner_id")
        return ", ".join(gaps) or None

    async def run(self, on_message, commands):
        self._on_message = on_message
        self._commands = commands
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
