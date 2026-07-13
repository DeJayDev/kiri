from kiri.transports import discorddm, terminal  # noqa: F401  -- registers them
from kiri.transports.base import TRANSPORTS


def build(name):
    if name not in TRANSPORTS:
        raise SystemExit(f"Unknown transport '{name}' (use: {', '.join(sorted(TRANSPORTS))})")
    return TRANSPORTS[name]()
