# Call

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/pregel/_algo/Call)

## Signature

```python
Call(
    self,
    func: Callable,
    input: tuple[tuple[Any, ...], dict[str, Any]],
    *,
    retry_policy: Sequence[RetryPolicy] | None,
    cache_policy: CachePolicy | None,
    callbacks: Callbacks,
    timeout: TimeoutPolicy | None = None,
)
```

## Constructors

```python
__init__(
    self,
    func: Callable,
    input: tuple[tuple[Any, ...], dict[str, Any]],
    *,
    retry_policy: Sequence[RetryPolicy] | None,
    cache_policy: CachePolicy | None,
    callbacks: Callbacks,
    timeout: TimeoutPolicy | None = None,
) -> None
```

| Name | Type |
|------|------|
| `func` | `Callable` |
| `input` | `tuple[tuple[Any, ...], dict[str, Any]]` |
| `retry_policy` | `Sequence[RetryPolicy] \| None` |
| `cache_policy` | `CachePolicy \| None` |
| `callbacks` | `Callbacks` |
| `timeout` | `TimeoutPolicy \| None` |


## Properties

- `func`
- `input`
- `retry_policy`
- `cache_policy`
- `callbacks`
- `timeout`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/pregel/_algo.py#L120)