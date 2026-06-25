import asyncio
import sqlite3
import time
from datetime import datetime, timezone

from croniter import croniter


def _next_run(cron):
    return croniter(cron, datetime.now(timezone.utc)).get_next(float)


class JobStore:
    def __init__(self, path):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cron TEXT NOT NULL,
                instruction TEXT NOT NULL,
                channel_id INTEGER NOT NULL,
                next_run REAL NOT NULL,
                created REAL NOT NULL
            )"""
        )
        self.db.commit()

    def add(self, cron, instruction, channel_id):
        cur = self.db.execute(
            "INSERT INTO jobs (cron, instruction, channel_id, next_run, created) VALUES (?,?,?,?,?)",
            (cron, instruction, channel_id, _next_run(cron), time.time()),
        )
        self.db.commit()
        return cur.lastrowid

    def list(self, channel_id):
        return self.db.execute(
            "SELECT * FROM jobs WHERE channel_id=? ORDER BY id", (channel_id,)
        ).fetchall()

    def delete(self, job_id, channel_id):
        cur = self.db.execute(
            "DELETE FROM jobs WHERE id=? AND channel_id=?", (job_id, channel_id)
        )
        self.db.commit()
        return cur.rowcount > 0

    def due(self, now):
        return self.db.execute(
            "SELECT * FROM jobs WHERE next_run<=?", (now,)
        ).fetchall()

    def reschedule(self, job_id, cron):
        self.db.execute(
            "UPDATE jobs SET next_run=? WHERE id=?", (_next_run(cron), job_id)
        )
        self.db.commit()


async def run_scheduler(store, execute):
    # execute(job_row) runs the stored instruction and delivers the result.
    while True:
        for job in store.due(time.time()):
            store.reschedule(job["id"], job["cron"])
            asyncio.create_task(execute(job))
        await asyncio.sleep(20)
