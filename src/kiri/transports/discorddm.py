import io
from contextlib import asynccontextmanager

import discord

from kiri import config
from kiri.transports.base import Inbound, Transport

_LIMIT = 2000

_intents = discord.Intents.default()
_intents.message_content = True
_intents.dm_messages = True


def _voice_attachment(message):
    if not message.flags.voice or not message.attachments:
        return None
    return message.attachments[0]


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
            Inbound(channel_id=message.channel.id, text=message.content.strip(), audio=audio)
        )


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

    async def ask(self, channel_id, question, options, multi_select):
        channel = await self._channel(channel_id)
        view = _AnswerView(question, options, multi_select)
        await channel.send(question[:_LIMIT], view=view)
        if await view.wait():
            return "error: the owner did not answer within an hour"
        return view.answer

    async def _write(self, channel, text):
        text = text or "(no output)"
        if len(text) <= _LIMIT:
            await channel.send(text)
            return
        buffer = io.BytesIO(text.encode("utf-8"))
        await channel.send("reply too long, attached.", file=discord.File(buffer, "reply.md"))

    @asynccontextmanager
    async def typing(self, channel_id):
        channel = await self._channel(channel_id)
        async with channel.typing():
            yield

    async def notify_owner(self, text):
        user = self._client.get_user(config.OWNER_ID) or await self._client.fetch_user(
            config.OWNER_ID
        )
        channel = user.dm_channel or await user.create_dm()
        await self._write(channel, text)
