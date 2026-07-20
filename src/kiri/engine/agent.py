from kiri.engine import llm
from kiri.tools.reload import Restart


async def run(session, user_text, registry, notify):
    if user_text is None:
        session.seal_dangling_tools()
    else:
        session.append_user(user_text)

    while True:
        # Before every request, so both tool loops and pure chat stay bounded.
        await session.maybe_compact()
        data = await llm.complete(session.system(), session.messages, registry.schemas())
        session.record_usage(data.get("usage", {}))

        content = data["content"]
        session.append_assistant(content)
        if data.get("stop_reason") != "tool_use":
            return llm.text_of(content)

        # Text the model wrote alongside its tool calls; only the final turn's text
        # is returned to the caller, so deliver this now or the owner never sees it.
        said = llm.text_of(content)
        if said:
            await notify(said)

        results = []
        for block in content:
            if block.get("type") != "tool_use":
                continue
            try:
                output = await registry.run(block["name"], block.get("input", {}))
            except Restart:
                # Append the reload tool_result before unwinding, or the saved turn
                # ends on a bare tool_use and 400s when the resume replays it.
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block["id"],
                    "content": "reloaded successfully - welcome back",
                })
                session.append_tool_results(results)
                raise
            results.append({"type": "tool_result", "tool_use_id": block["id"], "content": output})

        session.append_tool_results(results)
