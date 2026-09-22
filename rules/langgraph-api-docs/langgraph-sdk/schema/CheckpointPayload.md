# CheckpointPayload

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/schema/CheckpointPayload)

Payload for a checkpoint event.

## Signature

```python
CheckpointPayload()
```

## Extends

- `TypedDict`

## Constructors

```python
__init__(
    config: dict[str, Any] | None,
    metadata: dict[str, Any],
    values: dict[str, Any],
    next: list[str],
    parent_config: dict[str, Any] | None,
    tasks: list[CheckpointTaskPayload],
)
```

| Name | Type |
|------|------|
| `config` | `dict[str, Any] \| None` |
| `metadata` | `dict[str, Any]` |
| `values` | `dict[str, Any]` |
| `next` | `list[str]` |
| `parent_config` | `dict[str, Any] \| None` |
| `tasks` | `list[CheckpointTaskPayload]` |


## Properties

- `config`
- `metadata`
- `values`
- `next`
- `parent_config`
- `tasks`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/schema.py#L669)