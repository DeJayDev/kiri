from kiri.engine import llm


async def run(session, user_text, registry, on_usage=None):
    session.append_user(user_text)

    while True:
        # Before every request, so both tool loops and pure chat stay bounded.
        await session.maybe_compact()
        data = await llm.complete(session.system(), session.messages, registry.schemas())
        usage = data.get("usage", {})
        session.record_usage(usage)
        if on_usage:
            on_usage(usage)
        content = data["content"]
        session.append_assistant(content)

        if data.get("stop_reason") != "tool_use":
            return llm.text_of(content)

        results = []
        for block in content:
            if block.get("type") != "tool_use":
                continue
            output = await registry.run(block["name"], block.get("input", {}))
            results.append(
                {"type": "tool_result", "tool_use_id": block["id"], "content": output}
            )

        session.append_tool_results(results)
