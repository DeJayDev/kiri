import time

from kiri import config

_chat = None
_summarizer = None
_sink = None
_timer = None


def use(chat, summarizer=None, sink=None, timer=None):
    global _chat, _summarizer, _sink, _timer
    _chat = chat
    _summarizer = summarizer or chat
    _sink = sink
    _timer = timer


async def _run(provider, system, messages, tools, model, on_text=None):
    if provider is None:
        raise RuntimeError("no provider configured; app.start() wires this up")

    started = time.monotonic()
    first = None

    def first_text(delta):
        nonlocal first
        if first is None:
            first = time.monotonic()
        on_text(delta)

    name = f"{provider.name}/{model or config.MODEL}"
    ok = False
    try:
        data = await provider.complete(
            system, messages, tools, model=model, on_text=first_text if on_text else None
        )
        ok = True
    finally:
        if _timer:
            first_ms = None if first is None else (first - started) * 1000
            _timer("llm", name, (time.monotonic() - started) * 1000, ok, first_ms)

    # Every completion is billed, including the summarizer's. Reported here so the
    # sink doesn't have to be threaded through every caller.
    if _sink:
        _sink(data.get("usage", {}))
    return data


async def complete(system, messages, tools, model=None, on_text=None):
    return await _run(_chat, system, messages, tools, model, on_text)


async def summarize(system, messages, model=None):
    return await _run(_summarizer, system, messages, None, model)


def text_of(content):
    return "".join(b.get("text", "") for b in content if b.get("type") == "text").strip()
