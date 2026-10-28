import asyncio
import signal
import time
import traceback
from contextlib import AsyncExitStack

from kiri import clock, config, db, http, mcp_client, resume, spans, usage
from kiri.engine import conversation, llm, prompt
from kiri.engine.context import Session
from kiri.engine.providers import registry as providers
from kiri.engine.providers.base import AuthRequired
from kiri.engine.sessions import SessionStore
from kiri.scheduling.store import JobStore, run_scheduler
from kiri.skills import catalog
from kiri.tools.reload import Restart
from kiri.transports import registry as transports
from kiri.turns import Dispatcher


async def start():
    config.require()
    db.bind()

    chat = providers.build(config.PROVIDER)
    summarizer = providers.build(config.SUMMARY_PROVIDER) if config.SUMMARY_PROVIDER else chat
    llm.use(chat, summarizer, sink=usage.record, timer=spans.record)

    base_prompt = "\n\n".join(filter(None, [prompt.load(), catalog.index()]))
    sessions = SessionStore(base_prompt)
    store = JobStore()

    async with AsyncExitStack() as stack:
        stack.push_async_callback(http.aclose)
        mcp_tools = await mcp_client.load(config.MCP_CONFIG, stack)

        transport = transports.build(config.TRANSPORT)
        dispatcher = Dispatcher(transport, sessions, store, mcp_tools)

        async def execute(job):
            await execute_job(job, base_prompt, store, mcp_tools, dispatcher)

        async def execute_event(name, body):
            channel = await transport.owner_channel()
            instruction = f"An event arrived as {name}:\n\n{body}"
            await run_detached(channel, instruction, base_prompt, store, mcp_tools, dispatcher)

        async def supervised_scheduler():
            # A crash in the scheduler would otherwise die silently in its task;
            # surface it to the owner so reminders/jobs going dark is visible.
            try:
                await run_scheduler(store, execute, execute_event)
            except asyncio.CancelledError:
                raise
            except Exception:
                await transport.notify_owner(f"scheduler crashed:\n{traceback.format_exc()}")

        async def resume_pending():
            interrupted = resume.take_inflight()
            channel = resume.take()
            # This runs concurrently with transport.run(), so the first send of the
            # boot has to wait for the transport to be connected.
            if channel is None:
                if interrupted is not None:
                    await transport.ready()
                    await transport.send(
                        interrupted,
                        "I went down mid-turn without a clean shutdown. "
                        "Send /retry to pick up from the last checkpoint.",
                    )
                return
            await transport.ready()
            await transport.send(channel, "reloaded.")
            session = sessions.get(channel)
            try:
                reply = await conversation.run_turn(session, None, store, mcp_tools, transport)
            except Exception as exc:
                sessions.drop(channel)
                await transport.send(channel, f"error: {exc}")
                return
            sessions.save(session)
            if reply:
                await transport.send(channel, reply)

        serve = asyncio.create_task(transport.run(dispatcher.on_message))

        def graceful_stop():
            # systemd sends SIGTERM on stop/restart (SIGKILL only after the 90s
            # timeout). Save and mark a resume the way the reload tool does, so a
            # restart from anywhere -- owner, deploy, crash loop -- comes back and
            # finishes the turn instead of dropping it silently.
            sessions.flush()
            channel = dispatcher.active_channel()
            if channel is not None:
                resume.mark(channel)
            serve.cancel()

        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGTERM, graceful_stop)

        scheduler = asyncio.create_task(supervised_scheduler())
        resuming = asyncio.create_task(resume_pending())
        try:
            await serve
        except asyncio.CancelledError:
            pass
        finally:
            loop.remove_signal_handler(signal.SIGTERM)
            scheduler.cancel()
            resuming.cancel()


# A scheduled job runs with no owner watching, so a silent finish reads as a
# failure. Have it close every run with a status, even when nothing changed.
_JOB_REPORT = (
    "When you finish, end with one line stating what you checked and the result, "
    "even if nothing changed or there is nothing to do."
)


async def execute_job(job, base_prompt, store, mcp_tools, dispatcher):
    channel = job["channel_id"]
    late = time.time() - job["next_run"] > 60
    due = clock.stamp(job["next_run"])
    if job["cron"] is None:
        text = f"reminder: {job['instruction']}"
        if late:
            text += f"\n(late: it was due {due}, while I was down)"
        await dispatcher.transport.send(channel, text)
        dispatcher.sessions.get(channel).note(f"You sent the owner this reminder: {text}")
        return

    instruction = job["instruction"]
    if late:
        instruction = f"This job was due {due} and is running late because you were down.\n\n{instruction}"
    await run_detached(channel, instruction, base_prompt, store, mcp_tools, dispatcher)


async def run_detached(channel, instruction, base_prompt, store, mcp_tools, dispatcher):
    transport = dispatcher.transport
    session = None

    async def turn():
        nonlocal session
        # A fresh session per run, so it never pollutes the live DM conversation --
        # which is also why the retry below needs no rollback.
        session = Session(channel, base_prompt)
        text = f"{instruction}\n\n{_JOB_REPORT}"
        return await conversation.run_turn(session, text, store, mcp_tools, transport)

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
            await dispatcher.reauth(channel, exc.provider)
            reply = await turn()
        except Exception as retry_error:
            reply = f"job error: {retry_error}"
    except Exception as exc:
        reply = f"job error: {exc}"

    if reply is not None:
        await transport.send(channel, reply)
    dispatcher.sessions.archive(channel, [*session.archived, *session.messages])
    # None means the live preview already showed it; the run's session holds the text.
    delivered = reply if reply is not None else llm.text_of(session.messages[-1]["content"])
    note = f"While you were idle, this ran on its own:\n{instruction}\n\nIt sent the owner:\n{delivered}"
    dispatcher.sessions.get(channel).note(note)
