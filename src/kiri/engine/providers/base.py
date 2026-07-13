from dataclasses import dataclass

PROVIDERS = {}


class Provider:
    name = ""

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls.name:
            PROVIDERS[cls.name] = cls


class AuthRequired(Exception):
    def __init__(self, provider, message=""):
        super().__init__(message or f"{provider.name}: authentication required")
        self.provider = provider


class ProviderError(RuntimeError):
    def __init__(self, provider, status, body):
        super().__init__(f"{provider} {status}: {body}")
        self.status = status


@dataclass
class DeviceCode:
    device_code: str
    user_code: str
    verification_uri: str
    interval: float
    expires_at: float


def normalize_usage(input_tokens, output_tokens, cache_read=0, cache_write=0):
    # "input" means uncached on every provider. The session sizes its context from
    # the sum of all three; folding cached tokens into input breaks compaction.
    return {
        "input_tokens": max(input_tokens, 0),
        "output_tokens": max(output_tokens, 0),
        "cache_read_input_tokens": cache_read,
        "cache_creation_input_tokens": cache_write,
    }
