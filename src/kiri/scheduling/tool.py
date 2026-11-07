import time
from datetime import datetime

from croniter import croniter

from kiri import clock, config
from kiri.tools import shell


def _parse_when(value):
    text = str(value).strip()
    try:
        return float(text)
    except ValueError:
        pass
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=clock.zone())
    return dt.timestamp()


def _future(value, field):
    when = _parse_when(value)
    if when is None:
        return None, f"error: couldn't parse {field} '{value}' (use ISO 8601 like '2026-06-26T09:00:00' or epoch seconds)"
    if when <= time.time():
        return None, f"error: {field} is in the past"
    return when, None


SCHEDULE_SCHEMA = {
    "name": "schedule_job",
    "description": (
        "Persist a job, recurring with `cron` or once with `when`. When it fires, the "
        "stored instruction runs and the result is delivered to this DM."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "instruction": {"type": "string", "description": "What to run when it fires."},
            "cron": {
                "type": "string",
                "description": f"For a recurring job: 5-field cron in {config.TIMEZONE} (e.g. '0 9 * * *').",
            },
            "when": {
                "type": "string",
                "description": (
                    f"For a one-time job: ISO 8601 (e.g. '2026-06-26T09:00:00'), read as {config.TIMEZONE} "
                    "unless it carries an offset, or epoch seconds. Compute it from what the owner "
                    "said ('in 10 minutes', 'tomorrow 9am')."
                ),
            },
        },
        "required": ["instruction"],
    },
}

WATCH_SCHEMA = {
    "name": "watch",
    "description": (
        "Wait for something to become true, then act once and stop: 'tell me when X'. "
        "The condition runs on an interval with no model call; you are woken with the "
        "instruction only when it passes."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "condition": {
                "type": "string",
                "description": (
                    "Shell command that exits 0 once it is true and 1 while it is not yet. "
                    "Make any failure exit 2 or higher; that stops the watch and tells the owner."
                ),
            },
            "instruction": {"type": "string", "description": "What to do when it comes true."},
            "every_minutes": {"type": "integer", "description": "Minutes between checks. Defaults to 5."},
            "until": {
                "type": "string",
                "description": (
                    f"When to give up: ISO 8601, read as {config.TIMEZONE} unless it carries an "
                    "offset, or epoch seconds. Defaults to 24 hours from now."
                ),
            },
        },
        "required": ["condition", "instruction"],
    },
}

LIST_SCHEMA = {
    "name": "list_jobs",
    "description": "List this DM's scheduled jobs and watches.",
    "input_schema": {"type": "object", "properties": {}},
}

CANCEL_SCHEMA = {
    "name": "cancel_job",
    "description": "Cancel a scheduled job or watch by id.",
    "input_schema": {
        "type": "object",
        "properties": {"id": {"type": "integer"}},
        "required": ["id"],
    },
}


def build(store, channel_id):
    async def schedule(args):
        cron = (args.get("cron") or "").strip()
        if bool(cron) == bool(args.get("when")):
            return "error: pass exactly one of cron (recurring) or when (once)"
        if cron:
            if not croniter.is_valid(cron):
                return f"error: invalid cron '{cron}'"
            job_id = store.add(cron, args["instruction"], channel_id)
            return f"scheduled job {job_id}: '{cron}' -> {args['instruction']}"

        when, error = _future(args["when"], "when")
        if error:
            return error
        job_id = store.add_once(when, args["instruction"], channel_id)
        return f"scheduled job {job_id} for {clock.stamp(when)}: {args['instruction']}"

    async def watch(args):
        minutes = args.get("every_minutes", 5)
        if minutes < 1:
            return "error: every_minutes must be at least 1"
        expires = time.time() + 86400
        if args.get("until") is not None:
            expires, error = _future(args["until"], "until")
            if error:
                return error

        code, output = await shell.execute(args["condition"], 120)
        if code == 0:
            return f"no watch set: the condition is already true.\n{output}"
        if code != 1:
            return f"error: no watch set, the condition failed. It must exit 0 when true and 1 while not yet.\n{output}"
        job_id = store.add_watch(args["condition"], args["instruction"], channel_id, minutes * 60, expires)
        return f"watch {job_id} set, checking every {minutes} min until {clock.stamp(expires)}. First check:\n{output}"

    async def list_jobs(args):
        rows = store.list(channel_id)
        if not rows:
            return "no scheduled jobs"
        return "\n".join(_fmt_row(r) for r in rows)

    async def cancel(args):
        ok = store.delete(args["id"], channel_id)
        return f"cancelled job {args['id']}" if ok else f"no job {args['id']}"

    return [
        (SCHEDULE_SCHEMA, schedule),
        (WATCH_SCHEMA, watch),
        (LIST_SCHEMA, list_jobs),
        (CANCEL_SCHEMA, cancel),
    ]


def _fmt_row(row):
    if row["cron"]:
        return f"{row['id']}: '{row['cron']}' -> {row['instruction']}"
    if row["condition"]:
        until = clock.stamp(row["expires"])
        return f"{row['id']}: watch every {row['every'] // 60} min until {until}: `{row['condition']}` -> {row['instruction']}"
    return f"{row['id']}: once @ {clock.stamp(row['next_run'])} -> {row['instruction']}"
