# PregelNode

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/pregel/_read/PregelNode)

A node in a Pregel graph. This won't be invoked as a runnable by the graph
itself, but instead acts as a container for the components necessary to make
a PregelExecutableTask for a node.

## Signature

```python
PregelNode(
    self,
    *,
    channels: str | list[str],
    triggers: Sequence[str],
    mapper: Callable[[Any], Any] | None = None,
    writers: list[Runnable] | None = None,
    tags: list[str] | None = None,
    metadata: Mapping[str, Any] | None = None,
    bound: Runnable[Any, Any] | None = None,
    retry_policy: RetryPolicy | Sequence[RetryPolicy] | None = None,
    cache_policy: CachePolicy | None = None,
    is_error_handler: bool = False,
    error_handler_node: str | None = None,
    subgraphs: Sequence[PregelProtocol] | None = None,
    timeout: float | timedelta | TimeoutPolicy | None = None,
)
```

## Constructors

```python
__init__(
    self,
    *,
    channels: str | list[str],
    triggers: Sequence[str],
    mapper: Callable[[Any], Any] | None = None,
    writers: list[Runnable] | None = None,
    tags: list[str] | None = None,
    metadata: Mapping[str, Any] | None = None,
    bound: Runnable[Any, Any] | None = None,
    retry_policy: RetryPolicy | Sequence[RetryPolicy] | None = None,
    cache_policy: CachePolicy | None = None,
    is_error_handler: bool = False,
    error_handler_node: str | None = None,
    subgraphs: Sequence[PregelProtocol] | None = None,
    timeout: float | timedelta | TimeoutPolicy | None = None,
) -> None
```

| Name | Type |
|------|------|
| `channels` | `str \| list[str]` |
| `triggers` | `Sequence[str]` |
| `mapper` | `Callable[[Any], Any] \| None` |
| `writers` | `list[Runnable] \| None` |
| `tags` | `list[str] \| None` |
| `metadata` | `Mapping[str, Any] \| None` |
| `bound` | `Runnable[Any, Any] \| None` |
| `retry_policy` | `RetryPolicy \| Sequence[RetryPolicy] \| None` |
| `cache_policy` | `CachePolicy \| None` |
| `is_error_handler` | `bool` |
| `error_handler_node` | `str \| None` |
| `subgraphs` | `Sequence[PregelProtocol] \| None` |
| `timeout` | `float \| timedelta \| TimeoutPolicy \| None` |


## Properties

- `channels`
- `triggers`
- `mapper`
- `writers`
- `bound`
- `retry_policy`
- `cache_policy`
- `timeout`
- `tags`
- `metadata`
- `is_error_handler`
- `error_handler_node`
- `subgraphs`
- `flat_writers`
- `node`
- `input_cache_key`

## Methods

- [`copy()`](https://reference.langchain.com/python/langgraph/pregel/_read/PregelNode/copy)
- [`invoke()`](https://reference.langchain.com/python/langgraph/pregel/_read/PregelNode/invoke)
- [`ainvoke()`](https://reference.langchain.com/python/langgraph/pregel/_read/PregelNode/ainvoke)
- [`stream()`](https://reference.langchain.com/python/langgraph/pregel/_read/PregelNode/stream)
- [`astream()`](https://reference.langchain.com/python/langgraph/pregel/_read/PregelNode/astream)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/pregel/_read.py#L97)