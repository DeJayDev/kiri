import asyncio
from types import SimpleNamespace

import discord

from kiri.transports.discorddm import DiscordDM

BOT = SimpleNamespace(name="kiri")
OWNER = SimpleNamespace(name="owner")


class _Attachment:
    def __init__(self, filename, content_type, data=b""):
        self.filename = filename
        self.content_type = content_type
        self._data = data

    async def read(self):
        return self._data


class _Channel:
    def __init__(self, quoted):
        self.quoted = quoted

    async def fetch_message(self, message_id):
        if self.quoted is None:
            raise discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "gone")
        return self.quoted


def _client():
    client = DiscordDM()._client
    client._connection.user = BOT
    return client


def _reply_to(quoted):
    return SimpleNamespace(
        reference=SimpleNamespace(message_id=42),
        channel=_Channel(quoted),
    )


def _quote(message):
    return asyncio.run(_client()._quote(message))


def test_a_plain_message_has_no_quote():
    assert _quote(SimpleNamespace(reference=None)) is None


def test_a_reply_to_kiri_quotes_her_message():
    quoted = SimpleNamespace(author=BOT, content="3 PRs need review\nall green", attachments=[])

    assert _quote(_reply_to(quoted)) == "In reply to your message:\n> 3 PRs need review\n> all green"


def test_a_reply_to_the_owner_quotes_their_own_message():
    quoted = SimpleNamespace(author=OWNER, content="book the 9am", attachments=[])

    assert _quote(_reply_to(quoted)) == "In reply to my earlier message:\n> book the 9am"


def test_a_long_reply_attachment_is_read_into_the_quote():
    attachment = _Attachment("reply.md", "text/markdown; charset=utf-8", b"line one\nline two")
    quoted = SimpleNamespace(author=BOT, content="reply too long, attached.", attachments=[attachment])

    assert _quote(_reply_to(quoted)) == (
        "In reply to your message:\n> reply too long, attached.\n> line one\n> line two"
    )


def test_a_binary_attachment_is_named_not_read():
    attachment = _Attachment("chart.png", "image/png")
    quoted = SimpleNamespace(author=BOT, content="", attachments=[attachment])

    assert _quote(_reply_to(quoted)) == "In reply to your message:\n> [attachment: chart.png]"


def test_a_reply_to_a_deleted_message_says_so():
    assert _quote(_reply_to(None)) == "In reply to a message that has since been deleted."
