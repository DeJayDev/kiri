import asyncio

from kiri.engine import llm
from kiri.tools.reload import Restart


async def run(
    session, user_text, registry, notify, images=None, nudges=None, persist=None, live=None
):
    if user_text is None:
        session.seal_dangling_tools()
    else:
        session.append_user(user_text, images)

    async def take_nudges():
        # Owner messages that arrived mid-turn, drained once per loop step.
        if not nudges:
            return "", None
        return await nudges()

    while True:
        # Before every request, so both tool loops and pure chat stay bounded.
        await session.maybe_compact()
        # Checkpoint here and only here: the session always ends on a clean
        # boundary at loop top (never a half-emitted tool call), so a crash or a
        # process cutover mid-turn resumes from the last request instead of losing
        # the whole turn back to its last completed one.
        if persist:
            await persist()
        preview = live() if live else None
        try:
            data = await llm.complete(
                session.system(),
                session.messages,
                registry.schemas(),
                on_text=preview.feed if preview else None,
            )
        except BaseException:
            if preview:
                await preview.close(None)
            raise
        session.record_usage(data.get("usage", {}))

        content = data["content"]
        session.append_assistant(content)
        said = llm.text_of(content)
        # True when the streamed preview already shows the owner `said`; None is
        # returned for the final reply then, so the caller doesn't send it twice.
        shown = await preview.close(said) if preview else False

        if data.get("stop_reason") != "tool_use":
            text, imgs = await take_nudges()
            if not (text or imgs):
                return None if shown else said
            # The owner spoke while the model was finishing; deliver that reply and
            # keep going instead of ending the turn.
            if said and not shown:
                await notify(said)
            session.append_nudge(text, imgs)
            continue

        # Text the model wrote alongside its tool calls; only the final turn's text
        # is returned to the caller, so deliver this now or the owner never sees it.
        if said and not shown:
            await notify(said)

        calls = [block for block in content if block.get("type") == "tool_use"]
        outputs = await asyncio.gather(
            *(registry.run(block["name"], block.get("input", {})) for block in calls),
            return_exceptions=True,
        )

        results = []
        restart = None
        for block, output in zip(calls, outputs):
            if isinstance(output, Restart):
                restart = output
                output = "reloaded successfully - welcome back"
            elif isinstance(output, BaseException):
                raise output
            results.append({"type": "tool_result", "tool_use_id": block["id"], "content": output})

        if restart:
            # Append every tool_result before unwinding, or the saved turn ends on an
            # unanswered tool_use and 400s when the resume replays it.
            session.append_tool_results(results)
            raise restart

        text, imgs = await take_nudges()
        session.append_tool_results(results, text, imgs)
