import os

from kiri import config


def take():
    # Claimed by deleting before the run, so a crash mid-run never replays an event.
    # Writers must write elsewhere and rename in, or a half-written file is read.
    if not os.path.isdir(config.EVENTS_DIR):
        return []
    claimed = []
    for name in sorted(os.listdir(config.EVENTS_DIR)):
        if not name.endswith(".md") or name.startswith("."):
            continue
        path = os.path.join(config.EVENTS_DIR, name)
        with open(path) as f:
            body = f.read()
        os.remove(path)
        claimed.append((name, body))
    return claimed

