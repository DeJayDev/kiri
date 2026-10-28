import json
import os

from kiri import config


def _path():
    return os.path.join(config.KIRI_HOME, "resume.json")


def mark(channel_id):
    with open(_path(), "w") as f:
        json.dump({"channel_id": channel_id}, f)


def take():
    try:
        with open(_path()) as f:
            data = json.load(f)
    except FileNotFoundError:
        return None
    os.remove(_path())
    return data["channel_id"]


def clear():
    try:
        os.remove(_path())
    except FileNotFoundError:
        pass


# Written when a live turn starts and removed when it ends by any path the process
# survives. Still present at boot means the process died mid-turn.
def _inflight_path():
    return os.path.join(config.KIRI_HOME, "inflight.json")


def begin(channel_id):
    with open(_inflight_path(), "w") as f:
        json.dump({"channel_id": channel_id}, f)


def end():
    try:
        os.remove(_inflight_path())
    except FileNotFoundError:
        pass


def take_inflight():
    try:
        with open(_inflight_path()) as f:
            data = json.load(f)
    except FileNotFoundError:
        return None
    os.remove(_inflight_path())
    return data["channel_id"]
