import json
import os
import time

from kiri import config


def _load():
    if not os.path.exists(config.CREDENTIALS_PATH):
        return {}
    with open(config.CREDENTIALS_PATH) as f:
        return json.load(f)


def _write(data):
    path = config.CREDENTIALS_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    # 0600 at create, not chmod after -- that gap is world-readable.
    handle = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(handle, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def get(provider):
    return _load().get(provider)


def save(provider, record):
    data = _load()
    data[provider] = record
    _write(data)


def expires_in(record):
    if not record or not record.get("expires_at"):
        return None
    return record["expires_at"] - time.time()


def describe(provider):
    record = get(provider)
    if not record:
        return "no credentials"

    remaining = expires_in(record)
    refresh = "with refresh token" if record.get("refresh_token") else "no refresh token"
    if remaining is None:
        return f"logged in, no expiry recorded ({refresh})"
    if remaining <= 0:
        return f"expired {_duration(-remaining)} ago ({refresh})"
    return f"valid for {_duration(remaining)} ({refresh})"


def _duration(seconds):
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}m"
