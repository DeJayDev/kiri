import asyncio
import traceback
from contextlib import AsyncExitStack

from kiri import config, db, http, mcp_client, skills, transports, usage
from kiri.engine import conversation, llm, prompt, providers
from kiri.engine.context import Session
from kiri.engine.providers.base import AuthRequired
from kiri.engine.sessions import SessionStore
from kiri.scheduling.store import JobStore, run_scheduler
from kiri.tools.reload import Restart
from kiri.turns import Dispatcher


async def start():
    config.require()
    db.bind()

    chat = providers.build(config.PROVIDER)
    summarizer = providers.build(config.SUMMARY_PROVIDER) if config.SUMMARY_PROVIDER else chat
    llm.use(chat, summarizer, sink=usage.record)

    base_prompt = "\n\n".join(filter(None, [prompt.load(), skills.index()]))
    sessions = SessionStore(base_prompt)
    store = JobStore()

    async with AsyncExitStack() as stack:
        stack.push_async_callback(http.aclose)
        mcp_tools = await mcp_client.load(config.MCP_CONFIG, stack)

        transport = transports.build(config.TRANSPORT)
        dispatcher = Dispatcher(transport, sessions, store, mcp_tools)

        async def execute(job):
            await execute_job(job, base_prompt, store, mcp_tools, dispatcher)

        async def supervised_scheduler():
            # A crash in the scheduler would otherwise die silently in its task;
            # surface it to the owner so reminders/jobs going dark is visible.
            try:
                await run_scheduler(store, execute)
            except asyncio.CancelledError:
                raise
            except Exception:
                await transport.notify_owner(f"scheduler crashed:\n{traceback.format_exc()}")

        scheduler = asyncio.create_task(supervised_scheduler())
        try:
            await transport.run(dispatcher.on_message)
        finally:
            scheduler.cancel()


async def execute_job(job, base_prompt, store, mcp_tools, dispatcher):
    transport = dispatcher.transport
    if job["cron"] is None:
        await transport.send(job["channel_id"], f"reminder: {job['instruction']}")
        return

    async def turn():
        # A fresh session per job, so it never pollutes the live DM conversation --
        # which is also why the retry below needs no rollback.
        session = Session(job["channel_id"], base_prompt)
        return await conversation.run_turn(session, job["instruction"], store, mcp_tools)

    try:
        reply = await turn()
    except Restart:
        # A job has no owner watching, and restarting mid-turn would drop whatever
        # else is in flight. Reload is a live-conversation action.
        reply = "job error: reload not available from a job; ask in the DM"
    except AuthRequired as exc:
        # A job firing while the owner is asleep waits out the device code's expiry
        # and then fails: it never hangs, and never fires hours stale.
        try:
            await dispatcher.reauth(job["channel_id"], exc.provider)
            reply = await turn()
        except Exception as retry_error:
            reply = f"job error: {retry_error}"
    except Exception as exc:
        reply = f"job error: {exc}"
    await transport.send(job["channel_id"], reply)
