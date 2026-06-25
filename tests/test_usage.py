from kiri import usage


def test_record_and_tally_aggregates_by_day():
    usage.record({"input_tokens": 10, "output_tokens": 2})
    usage.record({"input_tokens": 5, "output_tokens": 1})
    usage.record({})  # empty usage is ignored

    rows = usage.tally()
    assert len(rows) == 1
    _day, input_tokens, output_tokens, calls = rows[0]
    assert input_tokens == 15
    assert output_tokens == 3
    assert calls == 2


def test_tally_empty():
    assert usage.tally() == []
