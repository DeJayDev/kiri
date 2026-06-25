import io

import discord

from ... import config


async def send(channel, text):
    text = text or "(no output)"
    if len(text) <= config.DISCORD_LIMIT:
        await channel.send(text)
        return
    buffer = io.BytesIO(text.encode("utf-8"))
    await channel.send("reply too long, attached.", file=discord.File(buffer, "reply.md"))
