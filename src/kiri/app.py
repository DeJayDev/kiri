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
from kiri.tools import shell
from kiri.tools.reload import Restart
from kiri.transports import registry as transports
from kiri.turns import COMMANDS, Dispatcher


async def start():
    config.require()
    db.bind()

    chat = providers.build(config.PROVIDER)
    summarizer = providers.build(config.SUMMARY_PROVIDER) if config.SUMMARY_PROVIDER else chat
    llm.use(chat, summarizer, sink=usage.record, timer=spans.record)

    transport = transports.build(config.TRANSPORT)
    base_prompt = "\n\n".join(filter(None, [prompt.load(), transport.style, catalog.index()]))
    sessions = SessionStore(base_prompt)
    store = JobStore()
    # Read before the scheduler starts, or this boot's own runs get reported as cut off.
    cut = list(db.Run.select().dicts())

    async with AsyncExitStack() as stack:
        stack.push_async_callback(http.aclose)
        mcp_tools, mcp_failed = await mcp_client.load(config.MCP_CONFIG, stack)

        dispatcher = Dispatcher(transport, sessions, store, mcp_tools)

        async def execute(job):
            await execute_job(job, base_prompt, store, mcp_tools, dispatcher)

        async def execute_event(name, body):
            channel = await transport.owner_channel()
            await run_detached(channel, body, base_prompt, store, mcp_tools, dispatcher)

        async def supervised_scheduler():
            # A crash in the scheduler would otherwise die silently in its task;
            # surface it to the owner so jobs going dark is visible.
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

        serve = asyncio.create_task(transport.run(dispatcher.on_message, COMMANDS))

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
        reporting = asyncio.create_task(report_cut_runs(cut, dispatcher))
        reporting_mcp = asyncio.create_task(report_failed_mcp(mcp_failed, dispatcher))
        try:
            await serve
        except asyncio.CancelledError:
            pass
        finally:
            loop.remove_signal_handler(signal.SIGTERM)
            scheduler.cancel()
            resuming.cancel()
            reporting.cancel()
            reporting_mcp.cancel()


async def report_failed_mcp(failed, dispatcher):
    if not failed:
        return
    await dispatcher.transport.ready()
    channel = await dispatcher.transport.owner_channel()
    listed = "\n".join(f"- {name}: {reason}" for name, reason in failed)
    await _tell(dispatcher, channel, f"These MCP servers failed to start, so their tools are missing until a reload:\n{listed}")


async def report_cut_runs(runs, dispatcher):
    if not runs:
        return
    await dispatcher.transport.ready()
    for run in runs:
        text = f"A restart cut off this background run before it finished:\n\n{run['instruction']}"
        await _tell(dispatcher, run["channel_id"], text)
        db.Run.delete_by_id(run["id"])


# A scheduled job runs with no owner watching, so a silent finish reads as a
# failure. Have it close every run with a status, even when nothing changed.
_JOB_REPORT = (
    "When you finish, end with one line stating what you checked and the result, "
    "even if nothing changed or there is nothing to do."
)


async def execute_job(job, base_prompt, store, mcp_tools, dispatcher):
    if job["condition"]:
        await check_watch(job, base_prompt, store, mcp_tools, dispatcher)
        return

    instruction = job["instruction"]
    if time.time() - job["next_run"] > 60:
        due = clock.stamp(job["next_run"])
        instruction = f"This job was due {due} and is running late because you were down.\n\n{instruction}"
    await run_detached(job["channel_id"], instruction, base_prompt, store, mcp_tools, dispatcher, report=True)


async def check_watch(job, base_prompt, store, mcp_tools, dispatcher):
    channel = job["channel_id"]
    code, output = await shell.execute(job["condition"], 120)
    last = time.time() + job["every"] > job["expires"]
    if code == 1 and not last:
        return
    if not store.complete(job["id"]):
        return

    if code == 0:
        text = (
            f"A watch you set just came true. Do what it asked: {job['instruction']}\n\n"
            f"Its condition:\n{job['condition']}\n{output}"
        )
        await run_detached(channel, text, base_prompt, store, mcp_tools, dispatcher)
        return
    if code == 1:
        until = clock.stamp(job["expires"])
        await _tell(dispatcher, channel, f"watch {job['id']} ran out at {until} without coming true. It was set to: {job['instruction']}")
        return
    await _tell(
        dispatcher,
        channel,
        f"watch {job['id']} stopped because its condition failed. It was set to: {job['instruction']}\n\n{output}",
    )


async def _tell(dispatcher, channel, text):
    await dispatcher.transport.send(channel, text)
    dispatcher.sessions.note(channel, f"You sent the owner this message: {text}")


async def run_detached(channel, instruction, base_prompt, store, mcp_tools, dispatcher, report=False):
    transport = dispatcher.transport
    session = None
    run = db.Run.create(channel_id=channel, instruction=instruction)
    # Registered so the owner's `stop` can reach it; every caller runs this in a task
    # of its own, so the task is the run.
    task = asyncio.current_task()
    dispatcher.background[task] = run
    task.add_done_callback(lambda done: dispatcher.background.pop(done, None))

    async def turn():
        nonlocal session
        # A fresh session per run, so it never pollutes the live DM conversation --
        # which is also why the retry below needs no rollback.
        session = Session(channel, base_prompt)
        text = f"{instruction}\n\n{_JOB_REPORT}" if report else instruction
        return await conversation.run_turn(session, text, store, mcp_tools, transport)

    failed = False
    try:
        reply = await turn()
    except Restart:
        # A job has no owner watching, and restarting mid-turn would drop whatever
        # else is in flight. Reload is a live-conversation action.
        failed = True
        reply = "job error: reload not available from a job; ask in the DM"
    except AuthRequired as exc:
        # A job firing while the owner is asleep waits out the device code's expiry
        # and then fails: it never hangs, and never fires hours stale.
        try:
            await dispatcher.reauth(channel, exc.provider)
            reply = await turn()
        except Exception as retry_error:
            failed = True
            reply = f"job error: {retry_error}"
    except Exception as exc:
        failed = True
        reply = f"job error: {exc}"

    if reply is not None:
        await transport.send(channel, reply)
    dispatcher.sessions.archive(channel, [*session.archived, *session.messages])
    # None means the live preview already showed it; the run's session holds the text.
    delivered = reply if reply is not None else llm.text_of(session.messages[-1]["content"])
    if failed:
        note = (
            "A background run failed, and the owner was already sent the error below. "
            f"Bring it up if it bears on what they say next.\n\nIt was running:\n{instruction}\n\n{delivered}"
        )
    else:
        note = (
            "A background run already sent the owner the text below, and they have it. "
            f"It is a record, not a message: do not reply to it or send it again.\n\n{delivered}"
        )
    dispatcher.sessions.note(channel, note)
    run.delete_instance()
