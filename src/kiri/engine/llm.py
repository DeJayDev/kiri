_chat = None
_summarizer = None
_sink = None


def use(chat, summarizer=None, sink=None):
    global _chat, _summarizer, _sink
    _chat = chat
    _summarizer = summarizer or chat
    _sink = sink


async def _run(provider, system, messages, tools, model):
    if provider is None:
        raise RuntimeError("no provider configured; app.start() wires this up")
    data = await provider.complete(system, messages, tools, model=model)
    # Every completion is billed, including the summarizer's. Reported here so the
    # sink doesn't have to be threaded through every caller.
    if _sink:
        _sink(data.get("usage", {}))
    return data


async def complete(system, messages, tools, model=None):
    return await _run(_chat, system, messages, tools, model)


async def summarize(system, messages, model=None):
    return await _run(_summarizer, system, messages, None, model)


def text_of(content):
    return "".join(b.get("text", "") for b in content if b.get("type") == "text").strip()
