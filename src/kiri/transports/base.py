from dataclasses import dataclass

TRANSPORTS = {}


class Transport:
    name = ""

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls.name:
            TRANSPORTS[cls.name] = cls

    async def ready(self):
        # Override where send() only works once run() has connected.
        return

    async def owner_channel(self):
        # Where unaddressed work, such as a dropped event file, reports.
        raise NotImplementedError

    def live(self, channel_id):
        # A streamed-reply preview: feed(delta) as text arrives, then close(final)
        # returns True when the preview now shows final. None means no streaming.
        return None


@dataclass
class Inbound:
    # The transport resolves its own quirks first: audio is raw bytes, not a
    # Discord attachment; images are (media_type, bytes) pairs.
    channel_id: int
    text: str
    audio: bytes | None = None
    images: list | None = None
    quote: str | None = None
    # Paths of other attachments, already saved to disk.
    files: list | None = None
