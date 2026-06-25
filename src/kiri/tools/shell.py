import asyncio

from .. import config

SCHEMA = {
    "name": "shell",
    "description": (
        "Run a command via the system shell on the owner's machine and return "
        "stdout, stderr, and exit code. The owner's full environment and PATH "
        "(including their custom binaries) are available."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Command line to execute."}
        },
        "required": ["command"],
    },
}


async def run(args):
    command = (args.get("command") or "").strip()
    if not command:
        return "error: empty command"

    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await proc.communicate()
    except asyncio.CancelledError:
        proc.kill()
        raise

    stdout = _cap(out.decode("utf-8", "replace"))
    stderr = _cap(err.decode("utf-8", "replace"))
    parts = [f"exit: {proc.returncode}"]
    if stdout:
        parts.append(f"stdout:\n{stdout}")
    if stderr:
        parts.append(f"stderr:\n{stderr}")
    return "\n".join(parts)


def _cap(text):
    if len(text) <= config.SHELL_OUTPUT_CAP:
        return text
    half = config.SHELL_OUTPUT_CAP // 2
    return f"{text[:half]}\n...[truncated]...\n{text[-half:]}"
