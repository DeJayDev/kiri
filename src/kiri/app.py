import asyncio
from contextlib import AsyncExitStack

from kiri import config, db, mcp_client
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
            # Jobs run in a fresh, standalone session so they never pollute the
            # live DM conversation.
            session = Session(job["channel_id"], base_prompt)
            try:
                reply = await conversation.run_turn(
                    session, job["instruction"], store, mcp_tools
                )
            except Exception as exc:
                reply = f"job error: {exc}"
            await bot.deliver(job["channel_id"], reply)

        asyncio.create_task(run_scheduler(store, execute))
        await bot.start(config.DISCORD_BOT_TOKEN)
