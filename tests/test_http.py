import asyncio

import httpx
import pytest

from kiri import http


def _response(status):
    return httpx.Response(status, request=httpx.Request("POST", "http://x"))


class _FakeClient:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    async def request(self, method, url, headers=None, json=None, data=None, timeout=None):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _timeout():
    return httpx.ReadTimeout("hung", request=httpx.Request("POST", "http://x"))


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def instant(_delay):
        return None

    monkeypatch.setattr(asyncio, "sleep", instant)


def _run(monkeypatch, outcomes):
    fake = _FakeClient(outcomes)
    monkeypatch.setattr(http, "client", lambda: fake)
    resp = asyncio.run(http.request("POST", "http://x"))
    return resp, fake


def test_retries_429_then_succeeds(monkeypatch):
    resp, fake = _run(monkeypatch, [_response(429), _response(200)])
    assert resp.status_code == 200
    assert fake.calls == 2


def test_retries_overloaded_and_connection_drops(monkeypatch):
    outcomes = [_response(529), httpx.ConnectError("boom"), _response(200)]
    resp, fake = _run(monkeypatch, outcomes)
    assert resp.status_code == 200
    assert fake.calls == 3


def test_does_not_retry_a_400(monkeypatch):
    resp, fake = _run(monkeypatch, [_response(400)])
    assert resp.status_code == 400
    assert fake.calls == 1


def test_gives_up_and_returns_the_last_response(monkeypatch):
    resp, fake = _run(monkeypatch, [_response(503)] * 4)
    assert resp.status_code == 503
    assert fake.calls == 4


def test_gives_up_and_raises_the_transport_error(monkeypatch):
    fake = _FakeClient([httpx.ConnectError("down")] * 4)
    monkeypatch.setattr(http, "client", lambda: fake)
    with pytest.raises(httpx.ConnectError):
        asyncio.run(http.request("POST", "http://x"))


def test_does_not_retry_a_read_timeout(monkeypatch):
    fake = _FakeClient([_timeout()])
    monkeypatch.setattr(http, "client", lambda: fake)
    with pytest.raises(httpx.ReadTimeout):
        asyncio.run(http.request("POST", "http://x"))
    assert fake.calls == 1


def test_retry_false_attempts_once(monkeypatch):
    fake = _FakeClient([_response(503)])
    monkeypatch.setattr(http, "client", lambda: fake)
    resp = asyncio.run(http.request("POST", "http://x", retry=False))
    assert resp.status_code == 503
    assert fake.calls == 1


class _State:
    # The slice of tenacity's RetryCallState that the wait function reads.
    def __init__(self, resp, attempt_number=3):
        self.outcome = _Outcome(resp)
        self.attempt_number = attempt_number
        self.idle_for = 0.0


class _Outcome:
    def __init__(self, resp):
        self.failed = False
        self._resp = resp

    def result(self):
        return self._resp


def test_retry_after_header_beats_the_backoff_curve():
    resp = httpx.Response(
        429, headers={"retry-after": "2.5"}, request=httpx.Request("POST", "http://x")
    )
    assert http._retry_after(resp) == 2.5
    assert http._wait(_State(resp)) == 2.5
    assert http._retry_after(_response(429)) is None


def test_retry_after_is_capped():
    resp = httpx.Response(
        429, headers={"retry-after": "3600"}, request=httpx.Request("POST", "http://x")
    )
    assert http._retry_after(resp) == 3600.0
    assert http._wait(_State(resp)) == 30.0
