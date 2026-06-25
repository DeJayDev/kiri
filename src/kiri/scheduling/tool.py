from croniter import croniter

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

LIST_SCHEMA = {
    "name": "list_jobs",
    "description": "List this DM's scheduled jobs.",
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

    async def list_jobs(args):
        rows = store.list(channel_id)
        if not rows:
            return "no scheduled jobs"
        return "\n".join(f"{r['id']}: '{r['cron']}' -> {r['instruction']}" for r in rows)

    async def cancel(args):
        ok = store.delete(args["id"], channel_id)
        return f"cancelled job {args['id']}" if ok else f"no job {args['id']}"

    return [
        (SCHEDULE_SCHEMA, schedule),
        (LIST_SCHEMA, list_jobs),
        (CANCEL_SCHEMA, cancel),
    ]
