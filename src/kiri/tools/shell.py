import asyncio
import os
import signal

from kiri import config

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
            "command": {"type": "string", "description": "Command line to execute."},
            "timeout": {
                "type": "integer",
                "description": (
                    "Seconds before the command is killed. Defaults to 120. Set it as "
                    "high as the command needs -- a long build, a big download, a heavy "
                    "query."
                ),
            },
        },
        "required": ["command"],
    },
}


async def run(args):
    command = (args.get("command") or "").strip()
    if not command:
        return "error: empty command"

    raw = args.get("timeout")
    try:
        timeout = 120 if raw is None else max(1, int(raw))
    except (TypeError, ValueError):
        return f"error: invalid timeout {raw!r} (whole seconds)"

    proc = await asyncio.create_subprocess_shell(
        _sourced(command),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        executable="/bin/bash",
        # Its own process group, so a timeout kills the whole tree and not just
        # the shell that spawned it.
        start_new_session=True,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        out, err = await _kill(proc)
        return _format(proc.returncode, out, err, timed_out=timeout)
    except asyncio.CancelledError:
        await _kill(proc)
        raise

    return _format(proc.returncode, out, err)


def _sourced(command):
    # The systemd unit runs with a minimal PATH; source the owner's login files so
    # ~/.local/bin and their custom bins resolve. The -r check and silenced stderr
    # are load-bearing: a missing or broken rc must not abort the command.
    return (
        'for __rc in "$HOME/.profile" "$HOME/.bash_profile" "$HOME/.bashrc"; do\n'
        '  [ -r "$__rc" ] && . "$__rc"\n'
        "done 2>/dev/null\n"
        f"{command}"
    )


async def _kill(proc):
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        proc.kill()

    # Best-effort: the pipes are mid-read after the abandoned communicate(), so
    # partial output can be lost.
    try:
        return await asyncio.wait_for(proc.communicate(), 5)
    except (TimeoutError, asyncio.CancelledError):
        return b"", b""


def _format(code, out, err, timed_out=None):
    if timed_out is None:
        parts = [f"exit: {code}"]
    else:
        parts = [
            f"error: killed after {timed_out}s. If it needs longer, run it again with a "
            "larger `timeout`. If it is hung or waiting on input, fix that instead."
        ]

    stdout = _cap(out.decode("utf-8", "replace"))
    stderr = _cap(err.decode("utf-8", "replace"))
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
