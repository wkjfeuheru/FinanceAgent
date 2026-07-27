"""为因超时失败的模型调用提供重试能力。"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable

from langchain.agents.middleware import wrap_model_call


DEFAULT_MAX_RETRIES = 2
DEFAULT_BACKOFF_SECONDS = 1.0


def _is_timeout_error(error: BaseException) -> bool:
    """识别内置超时异常以及常见 HTTP 客户端的超时异常。"""
    if isinstance(error, TimeoutError):
        return True
    return any(
        cls.__name__ in {"Timeout", "TimeoutError", "TimeoutException", "APITimeoutError"}
        for cls in type(error).__mro__
    )


def _backoff(attempt: int) -> float:
    return DEFAULT_BACKOFF_SECONDS * (2**attempt)


@wrap_model_call
def _retry_timed_out_model_call(request: Any, handler: Callable[[Any], Any]) -> Any:
    for attempt in range(DEFAULT_MAX_RETRIES + 1):
        try:
            return handler(request)
        except Exception as error:
            if not _is_timeout_error(error) or attempt == DEFAULT_MAX_RETRIES:
                raise
            time.sleep(_backoff(attempt))
    raise AssertionError("unreachable")


@wrap_model_call
async def _aretry_timed_out_model_call(
    request: Any,
    handler: Callable[[Any], Awaitable[Any]],
) -> Any:
    for attempt in range(DEFAULT_MAX_RETRIES + 1):
        try:
            return await handler(request)
        except Exception as error:
            if not _is_timeout_error(error) or attempt == DEFAULT_MAX_RETRIES:
                raise
            await asyncio.sleep(_backoff(attempt))
    raise AssertionError("unreachable")


# ``wrap_model_call`` 会分别为同步和异步执行模式创建 middleware 类。
# 合并这两个生成的类，使同一个 middleware 同时支持 invoke 和 ainvoke。
class ModelRetryMiddleware(
    type(_retry_timed_out_model_call),
    type(_aretry_timed_out_model_call),
):
    """同时支持同步和异步执行的模型超时重试 middleware。"""


model_retry = ModelRetryMiddleware()


__all__ = [
    "DEFAULT_BACKOFF_SECONDS",
    "DEFAULT_MAX_RETRIES",
    "ModelRetryMiddleware",
    "model_retry",
]
