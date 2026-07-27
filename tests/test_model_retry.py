import asyncio
import importlib

import pytest

from finance_agent.middleware import model_retry

retry_module = importlib.import_module("finance_agent.middleware.model_retry")


def test_sync_model_call_retries_timeout_twice(monkeypatch):
    calls = 0
    delays = []

    def handler(request):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise TimeoutError("model timed out")
        return "ok"

    monkeypatch.setattr(retry_module.time, "sleep", delays.append)

    assert model_retry.wrap_model_call(object(), handler) == "ok"
    assert calls == 3
    assert delays == [1.0, 2.0]


@pytest.mark.asyncio
async def test_async_model_call_retries_timeout_twice(monkeypatch):
    calls = 0
    delays = []

    async def handler(request):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise asyncio.TimeoutError("model timed out")
        return "ok"

    async def fake_sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(retry_module.asyncio, "sleep", fake_sleep)

    assert await model_retry.awrap_model_call(object(), handler) == "ok"
    assert calls == 3
    assert delays == [1.0, 2.0]


def test_non_timeout_error_is_not_retried(monkeypatch):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        raise ValueError("bad request")

    monkeypatch.setattr(retry_module.time, "sleep", lambda _: None)

    with pytest.raises(ValueError, match="bad request"):
        model_retry.wrap_model_call(object(), handler)
    assert calls == 1
