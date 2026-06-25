import asyncio
import time
from datetime import datetime, timezone

from croniter import croniter

from kiri.db import Job


def _next_run(cron):
    return croniter(cron, datetime.now(timezone.utc)).get_next(float)


class JobStore:
    def add(self, cron, instruction, channel_id):
        return Job.create(
            cron=cron,
            instruction=instruction,
            channel_id=channel_id,
            next_run=_next_run(cron),
            created=time.time(),
        ).id

    def add_once(self, when, instruction, channel_id):
        return Job.create(
            cron=None,
            instruction=instruction,
            channel_id=channel_id,
            next_run=when,
            created=time.time(),
        ).id

    def list(self, channel_id):
        return list(
            Job.select().where(Job.channel_id == channel_id).order_by(Job.id).dicts()
        )

    def delete(self, job_id, channel_id):
        return (
            Job.delete().where((Job.id == job_id) & (Job.channel_id == channel_id)).execute() > 0
        )

    def due(self, now):
        return list(Job.select().where(Job.next_run <= now).dicts())

    def reschedule(self, job_id, cron):
        Job.update(next_run=_next_run(cron)).where(Job.id == job_id).execute()

    def complete(self, job_id):
        Job.delete().where(Job.id == job_id).execute()


async def run_scheduler(store, execute):
    # execute(job_row) runs the stored instruction and delivers the result.
    while True:
        for job in store.due(time.time()):
            if job["cron"]:
                store.reschedule(job["id"], job["cron"])
            else:
                store.complete(job["id"])  # one-shot reminder, fire once
            asyncio.create_task(execute(job))
        await asyncio.sleep(20)
