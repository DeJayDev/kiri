from . import llm


async def run(session, user_text, registry):
    session.append_user(user_text)

    while True:
        data = await llm.complete(session.system(), session.messages, registry.schemas())
        session.record_usage(data.get("usage", {}))
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
        await session.maybe_compact()
