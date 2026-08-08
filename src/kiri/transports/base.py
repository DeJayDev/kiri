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


@dataclass
class Inbound:
    # The transport resolves its own quirks first: audio is raw bytes, not a
    # Discord attachment; images are (media_type, bytes) pairs.
    channel_id: int
    text: str
    audio: bytes | None = None
    images: list | None = None
