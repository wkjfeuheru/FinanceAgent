# call

> **Function** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/pregel/_call/call)

## Signature

```python
call(
    func: Callable[P, Awaitable[T]] | Callable[P, T],
    *args: Any = (),
    retry_policy: Sequence[RetryPolicy] | None = None,
    cache_policy: CachePolicy | None = None,
    timeout: float | timedelta | TimeoutPolicy | None = None,
    **kwargs: Any = {},
) -> SyncAsyncFuture[T]
```

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/pregel/_call.py#L258)