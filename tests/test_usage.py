from kiri import usage


def test_record_and_tally_aggregates_by_day():
    usage.record({"input_tokens": 10, "output_tokens": 2})
    usage.record({"input_tokens": 5, "output_tokens": 1})
    usage.record({})

    rows = usage.tally()
    assert len(rows) == 1
    _day, input_tokens, cache_write, cache_read, output_tokens, calls = rows[0]
    assert input_tokens == 15
    assert output_tokens == 3
    assert cache_write == 0
    assert cache_read == 0
    assert calls == 2


def test_record_tracks_cache_tokens():
    usage.record(
        {
            "input_tokens": 100,
            "output_tokens": 20,
            "cache_creation_input_tokens": 900,
            "cache_read_input_tokens": 8000,
        }
    )
    _day, input_tokens, cache_write, cache_read, _output, _calls = usage.tally()[0]
    assert (input_tokens, cache_write, cache_read) == (100, 900, 8000)
