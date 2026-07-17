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
