import asyncio
from types import SimpleNamespace

import discord

from kiri import config
from kiri.skills import catalog
from kiri.transports.discorddm import DiscordDM, _skill_names, _slash

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


def _dm(channel_id):
    channel = object.__new__(discord.DMChannel)
    channel.id = channel_id
    return channel


def _edit(before, after, author_id):
    author = SimpleNamespace(id=author_id)
    return (
        SimpleNamespace(content=before, channel=_dm(9), author=author),
        SimpleNamespace(content=after, channel=_dm(9), author=author),
    )


def _capture(client):
    received = []

    async def on_message(inbound):
        received.append(inbound)

    client.transport._on_message = on_message
    return received


def test_an_edit_reaches_kiri_with_the_old_text_quoted(monkeypatch):
    monkeypatch.setattr(config, "OWNER_ID", 7)
    client = _client()
    received = _capture(client)

    asyncio.run(client.on_message_edit(*_edit("weather in parsi", "weather in paris", 7)))

    [inbound] = received
    assert (inbound.channel_id, inbound.text) == (9, "weather in paris")
    assert inbound.quote == "This edits my earlier message, which read:\n> weather in parsi"


def test_an_edit_that_only_adds_a_link_preview_is_ignored(monkeypatch):
    monkeypatch.setattr(config, "OWNER_ID", 7)
    client = _client()
    received = _capture(client)

    asyncio.run(client.on_message_edit(*_edit("see https://x.dev", "see https://x.dev", 7)))

    assert received == []


def test_kiris_own_edited_messages_are_ignored(monkeypatch):
    monkeypatch.setattr(config, "OWNER_ID", 7)
    client = _client()
    received = _capture(client)

    asyncio.run(client.on_message_edit(*_edit("draft", "final", 99)))

    assert received == []


class _Response:
    def __init__(self):
        self.deferred = []

    async def defer(self, ephemeral=False):
        self.deferred.append(ephemeral)


class _Interaction:
    def __init__(self, user_id):
        self.user = SimpleNamespace(id=user_id)
        self.response = _Response()
        self.deleted = 0

    async def delete_original_response(self):
        self.deleted += 1


def _owner_dm(transport):
    async def owner_channel():
        return 9

    transport.owner_channel = owner_channel


def test_skill_is_one_dm_only_command_that_runs_the_named_skill(monkeypatch):
    monkeypatch.setattr(config, "OWNER_ID", 7)
    transport = DiscordDM()
    received = _capture(transport._client)
    _owner_dm(transport)
    interaction = _Interaction(7)

    command = _slash(transport, "skill", "Run one of your skills by name.", "skill")
    asyncio.run(command.callback(interaction, name="wttr", message="london"))

    assert command.allowed_contexts.dm_channel is True
    assert command.allowed_contexts.guild is not True
    assert [(p.name, p.required, p.autocomplete) for p in command.parameters] == [("name", True, True), ("message", False, False)]
    assert [(inbound.channel_id, inbound.text) for inbound in received] == [(9, "/wttr london")]


def test_skill_names_autocomplete_from_the_catalog(monkeypatch):
    monkeypatch.setattr(catalog, "descriptions", lambda: {"cheat": "Shell help.", "wttr": "Get weather."})

    choices = asyncio.run(_skill_names(None, "WT"))

    assert [(choice.name, choice.value) for choice in choices] == [("wttr: Get weather.", "wttr")]


def test_stop_and_new_ack_without_echoing_the_command(monkeypatch):
    monkeypatch.setattr(config, "OWNER_ID", 7)
    transport = DiscordDM()
    received = _capture(transport._client)
    _owner_dm(transport)
    interaction = _Interaction(7)

    asyncio.run(_slash(transport, "stop", "Stop the running turn.", None).callback(interaction))
    asyncio.run(_slash(transport, "new", "Start a fresh conversation.", None).callback(interaction))

    assert interaction.response.deferred == [True, True]
    assert interaction.deleted == 2
    assert [inbound.text for inbound in received] == ["/stop", "/new"]


def test_bg_needs_its_prompt_and_stop_takes_nothing():
    transport = DiscordDM()

    bg = _slash(transport, "bg", "Run a prompt in the background.", "prompt")
    stop = _slash(transport, "stop", "Stop the running turn.", None)

    assert [(p.name, p.required) for p in bg.parameters] == [("prompt", True)]
    assert stop.parameters == []


def test_a_command_from_anyone_but_the_owner_does_nothing(monkeypatch):
    monkeypatch.setattr(config, "OWNER_ID", 7)
    transport = DiscordDM()
    received = _capture(transport._client)
    interaction = _Interaction(8)

    asyncio.run(_slash(transport, "new", "Start a fresh conversation.", None).callback(interaction))

    assert interaction.response.deferred == []
    assert received == []
