# SyncEventStreamHandle

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/stream/transport/base/SyncEventStreamHandle)

Handle for one sync filtered event stream.

## Signature

```python
SyncEventStreamHandle(
    self,
    events: Iterator[Event],
    error: Callable[[], BaseException | None],
    close: Callable[[], None],
)
```

## Constructors

```python
__init__(
    self,
    events: Iterator[Event],
    error: Callable[[], BaseException | None],
    close: Callable[[], None],
) -> None
```

| Name | Type |
|------|------|
| `events` | `Iterator[Event]` |
| `error` | `Callable[[], BaseException \| None]` |
| `close` | `Callable[[], None]` |


## Properties

- `events`
- `error`
- `close`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/stream/transport/base.py#L24)