# StateNodeSpec

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/graph/_node/StateNodeSpec)

## Signature

```python
StateNodeSpec(
    self,
    runnable: StateNode[NodeInputT, ContextT],
    metadata: dict[str, Any] | None,
    input_schema: type[NodeInputT],
    retry_policy: RetryPolicy | Sequence[RetryPolicy] | None,
    cache_policy: CachePolicy | None,
    is_error_handler: bool = False,
    error_handler_node: str | None = None,
    ends: tuple[str, ...] | dict[str, str] | None = EMPTY_SEQ,
    defer: bool = False,
    timeout: TimeoutPolicy | None = None,
)
```

## Extends

- `Generic[NodeInputT, ContextT]`

## Constructors

```python
__init__(
    self,
    runnable: StateNode[NodeInputT, ContextT],
    metadata: dict[str, Any] | None,
    input_schema: type[NodeInputT],
    retry_policy: RetryPolicy | Sequence[RetryPolicy] | None,
    cache_policy: CachePolicy | None,
    is_error_handler: bool = False,
    error_handler_node: str | None = None,
    ends: tuple[str, ...] | dict[str, str] | None = EMPTY_SEQ,
    defer: bool = False,
    timeout: TimeoutPolicy | None = None,
) -> None
```

| Name | Type |
|------|------|
| `runnable` | `StateNode[NodeInputT, ContextT]` |
| `metadata` | `dict[str, Any] \| None` |
| `input_schema` | `type[NodeInputT]` |
| `retry_policy` | `RetryPolicy \| Sequence[RetryPolicy] \| None` |
| `cache_policy` | `CachePolicy \| None` |
| `is_error_handler` | `bool` |
| `error_handler_node` | `str \| None` |
| `ends` | `tuple[str, ...] \| dict[str, str] \| None` |
| `defer` | `bool` |
| `timeout` | `TimeoutPolicy \| None` |


## Properties

- `runnable`
- `metadata`
- `input_schema`
- `retry_policy`
- `cache_policy`
- `is_error_handler`
- `error_handler_node`
- `ends`
- `defer`
- `timeout`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/graph/_node.py#L84)