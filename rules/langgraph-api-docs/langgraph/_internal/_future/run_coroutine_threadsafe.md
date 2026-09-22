# run_coroutine_threadsafe

> **Function** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/_internal/_future/run_coroutine_threadsafe)

Submit a coroutine object to a given event loop.

Return an asyncio.Future to access the result.

## Signature

```python
run_coroutine_threadsafe(
    coro: Coroutine[None, None, T],
    loop: asyncio.AbstractEventLoop,
    *,
    lazy: bool,
    name: str | None = None,
    context: contextvars.Context | None = None,
) -> asyncio.Future[T]
```

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/_internal/_future.py#L189)