# SyncRunModule

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/_sync/stream/SyncRunModule)

Command dispatcher for `run.start`.

Bound to one `SyncThreadStream`; accesses its transport and id allocator.

## Signature

```python
SyncRunModule(
    self,
    owner: SyncThreadStream,
)
```

## Constructors

```python
__init__(
    self,
    owner: SyncThreadStream,
) -> None
```

| Name | Type |
|------|------|
| `owner` | `SyncThreadStream` |


## Methods

- [`start()`](https://reference.langchain.com/python/langgraph-sdk/_sync/stream/SyncRunModule/start)
- [`respond()`](https://reference.langchain.com/python/langgraph-sdk/_sync/stream/SyncRunModule/respond)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/_sync/stream.py#L203)