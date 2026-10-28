import asyncio
import time

import peewee
from croniter import croniter

from kiri import clock
from kiri.db import Job
from kiri.scheduling import events


def _next_run(cron):
    # Evaluated in the owner's zone, so "0 9 * * *" stays 9am across DST.
    return croniter(cron, clock.now()).get_next(float)


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

    def next_due(self):
        return Job.select(peewee.fn.MIN(Job.next_run)).scalar()

    def reschedule(self, job_id, cron):
        Job.update(next_run=_next_run(cron)).where(Job.id == job_id).execute()

    def complete(self, job_id):
        Job.delete().where(Job.id == job_id).execute()


async def run_scheduler(store, execute, execute_event):
    # execute(job_row) runs the stored instruction and delivers the result;
    # execute_event(name, body) runs a file dropped in the events dir.
    running = set()

    def launch(coro):
        task = asyncio.create_task(coro)
        # The event loop holds tasks weakly; an unreferenced one can be garbage
        # collected mid-run and the job silently never finishes.
        running.add(task)
        task.add_done_callback(running.discard)

    while True:
        for job in store.due(time.time()):
            if job["cron"]:
                store.reschedule(job["id"], job["cron"])
            else:
                store.complete(job["id"])  # one-shot reminder, fire once
            launch(execute(job))
        for name, body in events.take():
            launch(execute_event(name, body))

        # Sleep exactly to the next job, but no longer than a few seconds so new
        # jobs and dropped event files are picked up promptly.
        upcoming = store.next_due()
        wait = 5 if upcoming is None else min(max(upcoming - time.time(), 0), 5)
        await asyncio.sleep(wait)
