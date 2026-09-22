# Checkpoint

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/schema/Checkpoint)

Represents a checkpoint in the execution process.

## Signature

```python
Checkpoint()
```

## Extends

- `TypedDict`

## Constructors

```python
__init__(
    thread_id: str,
    checkpoint_ns: str,
    checkpoint_id: str | None,
    checkpoint_map: dict[str, Any] | None,
)
```

| Name | Type |
|------|------|
| `thread_id` | `str` |
| `checkpoint_ns` | `str` |
| `checkpoint_id` | `str \| None` |
| `checkpoint_map` | `dict[str, Any] \| None` |


## Properties

- `thread_id`
- `checkpoint_ns`
- `checkpoint_id`
- `checkpoint_map`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/schema.py#L208)