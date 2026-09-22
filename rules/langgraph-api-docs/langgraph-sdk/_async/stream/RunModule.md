# RunModule

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/_async/stream/RunModule)

Command dispatcher for `run.start`.

Bound to one `AsyncThreadStream`; accesses its transport and id allocator.

## Signature

```python
RunModule(
    self,
    owner: AsyncThreadStream,
)
```

## Constructors

```python
__init__(
    self,
    owner: AsyncThreadStream,
) -> None
```

| Name | Type |
|------|------|
| `owner` | `AsyncThreadStream` |


## Methods

- [`start()`](https://reference.langchain.com/python/langgraph-sdk/_async/stream/RunModule/start)
- [`respond()`](https://reference.langchain.com/python/langgraph-sdk/_async/stream/RunModule/respond)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/_async/stream.py#L160)