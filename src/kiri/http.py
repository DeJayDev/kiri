import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    retry_if_result,
    stop_after_attempt,
    wait_exponential_jitter,
)

_client = None

# Statuses that carry no information. A 400 or a bad key is a real answer.
_RETRY_STATUS = {408, 429, 500, 502, 503, 504, 529}


def client():
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(600.0),
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
        )
    return _client


async def aclose():
    global _client
    if _client is None:
        return
    await _client.aclose()
    _client = None


def _retry_after(resp):
    if not isinstance(resp, httpx.Response):
        return None
    value = resp.headers.get("retry-after")
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None  # the HTTP-date form; fall back to the curve


def _wait(state):
    # A server that told us when to come back beats our curve -- but capped, or a
    # `Retry-After: 3600` would sit on the turn for an hour with the channel
    # serialized behind it.
    outcome = state.outcome
    if outcome is not None and not outcome.failed:
        delay = _retry_after(outcome.result())
        if delay is not None:
            return min(delay, 30.0)
    return wait_exponential_jitter(initial=1.0, max=30.0)(state)


def _last_outcome(state):
    # Hand back the final response, or re-raise the transport error it died on.
    # Never a tenacity RetryError wrapper.
    return state.outcome.result()


def _retryable(exc):
    # A read timeout stacks: four of them is four full timeouts on one turn.
    if isinstance(exc, httpx.ReadTimeout | httpx.WriteTimeout):
        return False
    return isinstance(exc, httpx.TransportError)


async def request(
    method, url, headers=None, json=None, data=None, timeout=None, retry=True
) -> httpx.Response:
    async def attempt():
        return await client().request(
            method, url, headers=headers, json=json, data=data, timeout=timeout
        )

    retrying = AsyncRetrying(
        stop=stop_after_attempt(4 if retry else 1),
        wait=_wait,
        retry=(
            retry_if_exception(_retryable)
            | retry_if_result(lambda resp: resp.status_code in _RETRY_STATUS)
        ),
        retry_error_callback=_last_outcome,
    )
    return await retrying(attempt)
