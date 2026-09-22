# ScopedStreamHandle

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/_async/stream/ScopedStreamHandle)

Scoped streaming handle for one discovered child invocation.

## Signature

```python
ScopedStreamHandle(
    self,
    *,
    thread: AsyncThreadStream,
    path: tuple[str, ...],
    graph_name: str | None,
    trigger_call_id: str | None,
    max_queue_size: int = 0,
)
```

## Constructors

```python
__init__(
    self,
    *,
    thread: AsyncThreadStream,
    path: tuple[str, ...],
    graph_name: str | None,
    trigger_call_id: str | None,
    max_queue_size: int = 0,
) -> None
```

| Name | Type |
|------|------|
| `thread` | `AsyncThreadStream` |
| `path` | `tuple[str, ...]` |
| `graph_name` | `str \| None` |
| `trigger_call_id` | `str \| None` |
| `max_queue_size` | `int` |


## Properties

- `path`
- `namespace`
- `graph_name`
- `trigger_call_id`
- `status`
- `error`
- `messages`
- `tool_calls`
- `subgraphs`
- `subagents`
- `extensions`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/_async/stream.py#L544)