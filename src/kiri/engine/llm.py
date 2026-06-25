from . import providers


async def complete(system, messages, tools):
    return await providers.complete(system, messages, tools)


def text_of(content):
    return "".join(b.get("text", "") for b in content if b.get("type") == "text").strip()
