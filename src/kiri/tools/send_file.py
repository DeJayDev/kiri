import os

SCHEMA = {
    "name": "send_file",
    "description": (
        "Send a file from this machine to the owner as an attachment: a chart, PDF, "
        "screenshot, or anything they should open rather than read inline."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Absolute path to the file."}},
        "required": ["path"],
    },
}


def build(transport, channel_id):
    async def send_file(args):
        path = os.path.expanduser(args["path"])
        if not os.path.isfile(path):
            return f"error: no file at {path}"
        error = await transport.send_file(channel_id, path)
        return error or f"sent {os.path.basename(path)}"

    return send_file
