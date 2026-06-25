import asyncio
import traceback
from contextlib import AsyncExitStack

from kiri import config, db, mcp_client, usage
from kiri.engine import conversation, prompt
from kiri.engine.context import Session
from kiri.engine.sessions import SessionStore
from kiri.scheduling.store import JobStore, run_scheduler
from kiri.transports.discord.client import Kiri


async def start():
    config.require()
    db.bind()
    base_prompt = prompt.load()
    sessions = SessionStore(base_prompt)
    store = JobStore()

    async with AsyncExitStack() as stack:
        mcp_tools = await mcp_client.load(config.MCP_CONFIG, stack)
        bot = Kiri(sessions, store, mcp_tools)

        async def execute(job):
            await execute_job(job, base_prompt, store, mcp_tools, bot, on_usage=usage.record)

        async def supervised_scheduler():
            # A crash in the scheduler would otherwise die silently in its task;
            # surface it to the owner so reminders/jobs going dark is visible.
            try:
                await run_scheduler(store, execute)
            except asyncio.CancelledError:
                raise
            except Exception:
                await bot.notify_owner(f"scheduler crashed:\n{traceback.format_exc()}")

        asyncio.create_task(supervised_scheduler())
        await bot.start(config.DISCORD_BOT_TOKEN)


async def execute_job(job, base_prompt, store, mcp_tools, bot, on_usage=None):
    if job["cron"] is None:
        await bot.deliver(job["channel_id"], f"Reminder: {job['instruction']}")
        return

    # Jobs run in a fresh, standalone session so they never pollute the live DM
    # conversation.
    session = Session(job["channel_id"], base_prompt)
    try:
        reply = await conversation.run_turn(
            session, job["instruction"], store, mcp_tools, on_usage=on_usage
        )
    except Exception as exc:
        reply = f"job error: {exc}"
    await bot.deliver(job["channel_id"], reply)
