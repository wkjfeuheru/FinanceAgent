# NodeTimeoutError

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/errors/NodeTimeoutError)

Raised when a node invocation exceeds one of its configured timeouts.

Does **not** inherit from the built-in `TimeoutError` (a subclass of
`OSError`) so that the default `RetryPolicy` treats it as retryable.

Both `idle_timeout` and `run_timeout` reflect the configured policy at the
time of the failure (each is `None` if not configured). `kind` and
`timeout` identify which one fired.

## Signature

```python
NodeTimeoutError(
    self,
    node: str,
    elapsed: float,
    *,
    kind: Literal['idle', 'run'],
    idle_timeout: float | None = None,
    run_timeout: float | None = None,
)
```

## Extends

- `Exception`

## Constructors

```python
__init__(
    self,
    node: str,
    elapsed: float,
    *,
    kind: Literal['idle', 'run'],
    idle_timeout: float | None = None,
    run_timeout: float | None = None,
) -> None
```

| Name | Type |
|------|------|
| `node` | `str` |
| `elapsed` | `float` |
| `kind` | `Literal['idle', 'run']` |
| `idle_timeout` | `float \| None` |
| `run_timeout` | `float \| None` |


## Properties

- `node`
- `timeout`
- `run_timeout`
- `idle_timeout`
- `elapsed`
- `kind`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/errors.py#L190)