import time
from datetime import datetime, timezone

from croniter import croniter


def _parse_when(value):
    text = str(value).strip()
    try:
        return float(text)  # epoch seconds
    except ValueError:
        pass
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _fmt_utc(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


SCHEDULE_SCHEMA = {
    "name": "schedule_job",
    "description": (
        "Persist a recurring job. When it fires, the stored instruction runs and "
        "the result is delivered to this DM. Cron is standard 5-field, UTC."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "cron": {"type": "string", "description": "5-field cron, UTC (e.g. '0 13 * * *')."},
            "instruction": {"type": "string", "description": "What to run when it fires."},
        },
        "required": ["cron", "instruction"],
    },
}

REMIND_SCHEMA = {
    "name": "remind",
    "description": (
        "Set a one-shot reminder. At the given time the instruction runs once and "
        "the result is delivered to this DM, then the reminder is deleted. You "
        "compute the absolute UTC time from whatever the user said (e.g. 'in 10 "
        "minutes', 'tomorrow 9am') and pass it here."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "when": {
                "type": "string",
                "description": "Absolute time: ISO 8601 UTC (e.g. '2026-06-26T09:00:00Z') or epoch seconds.",
            },
            "instruction": {"type": "string", "description": "What to run when it fires."},
        },
        "required": ["when", "instruction"],
    },
}

LIST_SCHEMA = {
    "name": "list_jobs",
    "description": "List this DM's scheduled jobs and reminders.",
    "input_schema": {"type": "object", "properties": {}},
}

CANCEL_SCHEMA = {
    "name": "cancel_job",
    "description": "Cancel a scheduled job by id.",
    "input_schema": {
        "type": "object",
        "properties": {"id": {"type": "integer"}},
        "required": ["id"],
    },
}


def build(store, channel_id):
    async def schedule(args):
        cron = args["cron"].strip()
        if not croniter.is_valid(cron):
            return f"error: invalid cron '{cron}'"
        job_id = store.add(cron, args["instruction"], channel_id)
        return f"scheduled job {job_id}: '{cron}' -> {args['instruction']}"

    async def remind(args):
        when = _parse_when(args["when"])
        if when is None:
            return (
                f"error: couldn't parse when '{args['when']}' "
                "(use ISO 8601 UTC like '2026-06-26T09:00:00Z' or epoch seconds)"
            )
        if when <= time.time():
            return "error: that time is in the past"
        job_id = store.add_once(when, args["instruction"], channel_id)
        return f"reminder {job_id} set for {_fmt_utc(when)}: {args['instruction']}"

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
        (REMIND_SCHEMA, remind),
        (LIST_SCHEMA, list_jobs),
        (CANCEL_SCHEMA, cancel),
    ]


def _fmt_row(row):
    if row["cron"]:
        return f"{row['id']}: '{row['cron']}' -> {row['instruction']}"
    return f"{row['id']}: once @ {_fmt_utc(row['next_run'])} -> {row['instruction']}"
