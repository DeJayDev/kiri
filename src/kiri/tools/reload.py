import os
import sys


class Restart(Exception):
    pass


SCHEMA = {
    "name": "reload",
    "description": (
        "Reload yourself so that changes to your prompt, config, tools or MCP "
        "servers take effect. Use it after you or the owner edit any of those. "
        "The turn you are in ends here; the owner talks to you again afterwards."
    ),
    "input_schema": {"type": "object", "properties": {}},
}


async def run(args):
    raise Restart()


def restart():
    # Through the interpreter, not argv[0]: a console script installed by uv is not
    # necessarily re-execable, and execv does no PATH lookup. Replaces this process
    # image, so nothing after this line runs -- an OSError here is the caller's to
    # report, because by then it has already said "reloading...".
    os.execv(sys.executable, [sys.executable, "-m", "kiri", *sys.argv[1:]])
