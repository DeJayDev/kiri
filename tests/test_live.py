import asyncio

from kiri.transports.discorddm import _Live


class _Message:
    def __init__(self, content):
        self.content = content
        self.deleted = False

    async def edit(self, content):
        self.content = content

    async def delete(self):
        self.deleted = True


class _Channel:
    def __init__(self):
        self.messages = []

    async def send(self, text):
        message = _Message(text)
        self.messages.append(message)
        return message


class _Transport:
    def __init__(self):
        self.channel = _Channel()

    async def _channel(self, channel_id):
        return self.channel


def _stream(final, wait=1.2):
    transport = _Transport()
    live = _Live(transport, 1)

    async def go():
        live.feed("partial ")
        live.feed("text")
        await asyncio.sleep(wait)
        return await live.close(final)

    return asyncio.run(go()), transport.channel.messages


def test_the_preview_becomes_the_final_reply():
    shown, messages = _stream("partial text, finished")
    assert shown is True
    assert [m.content for m in messages] == ["partial text, finished"]


def test_a_reply_too_long_for_one_message_deletes_the_preview():
    shown, messages = _stream("x" * 2001)
    assert shown is False
    assert messages[0].deleted


def test_an_aborted_turn_deletes_the_preview():
    shown, messages = _stream(None)
    assert shown is False
    assert messages[0].deleted


def test_a_reply_faster_than_the_first_edit_never_previews():
    shown, messages = _stream("quick", wait=0)
    assert shown is False
    assert messages == []
