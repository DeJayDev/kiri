import asyncio

from kiri.tools import ask
from kiri.transports import terminal

_WHEN = [{"label": "monday", "description": "start of the week"}, {"label": "tuesday"}]


class _Transport:
    def __init__(self, answer):
        self.answer = answer
        self.asked = []

    async def ask(self, channel_id, question, options, multi_select):
        self.asked.append((channel_id, question, options, multi_select))
        return self.answer


def test_ask_passes_question_and_options_to_transport():
    transport = _Transport("tuesday")
    run = ask.build(transport, 7)

    answer = asyncio.run(run({"question": "when?", "options": _WHEN, "multi_select": True}))

    assert answer == "tuesday"
    assert transport.asked == [(7, "when?", _WHEN, True)]


def test_ask_defaults_to_single_select():
    transport = _Transport("monday")
    run = ask.build(transport, 7)

    asyncio.run(run({"question": "when?", "options": _WHEN}))

    assert transport.asked == [(7, "when?", _WHEN, False)]


def test_ask_without_options_is_an_error():
    transport = _Transport("x")
    answer = asyncio.run(ask.build(transport, 7)({"question": "when?", "options": []}))

    assert "error" in answer
    assert transport.asked == []


def test_ask_with_more_than_five_options_is_an_error():
    transport = _Transport("x")
    options = [{"label": str(n)} for n in range(6)]
    answer = asyncio.run(ask.build(transport, 7)({"question": "when?", "options": options}))

    assert "at most 5" in answer
    assert transport.asked == []


def test_ask_allows_exactly_five_options():
    transport = _Transport("3")
    options = [{"label": str(n)} for n in range(5)]
    asyncio.run(ask.build(transport, 7)({"question": "when?", "options": options}))

    assert transport.asked == [(7, "when?", options, False)]


def test_ask_reports_an_empty_answer_as_an_error():
    run = ask.build(_Transport(""), 7)
    assert "error" in asyncio.run(run({"question": "when?", "options": _WHEN}))


def test_terminal_maps_a_number_to_its_option_label(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt: "2")
    assert asyncio.run(terminal.Terminal().ask(0, "when?", _WHEN, False)) == "tuesday"


def test_terminal_takes_free_text_over_the_options(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt: "  friday  ")
    assert asyncio.run(terminal.Terminal().ask(0, "when?", _WHEN, False)) == "friday"


def test_terminal_joins_a_multi_select_pick(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt: "1, 2")
    assert asyncio.run(terminal.Terminal().ask(0, "when?", _WHEN, True)) == "monday, tuesday"


def test_terminal_reads_a_comma_list_as_free_text_when_single_select(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt: "1, 2")
    assert asyncio.run(terminal.Terminal().ask(0, "when?", _WHEN, False)) == "1, 2"


def test_terminal_ignores_a_number_with_no_matching_option(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt: "9")
    assert asyncio.run(terminal.Terminal().ask(0, "when?", _WHEN, False)) == "9"


def test_terminal_shows_the_option_descriptions(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda prompt: "1")
    asyncio.run(terminal.Terminal().ask(0, "when?", _WHEN, False))
    assert "start of the week" in capsys.readouterr().out
