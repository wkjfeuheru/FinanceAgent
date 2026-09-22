# CheckpointTaskPayload

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/schema/CheckpointTaskPayload)

A task entry within a `CheckpointPayload`.

The keys present depend on the task's state:

- **Error:** `id`, `name`, `error`, `state`
- **Has result:** `id`, `name`, `result`, `interrupts`, `state`
- **Pending:** `id`, `name`, `interrupts`, `state`

## Signature

```python
CheckpointTaskPayload()
```

## Extends

- `TypedDict`

## Constructors

```python
__init__(
    id: str,
    name: str,
    error: NotRequired[str],
    result: NotRequired[Any],
    interrupts: NotRequired[list[dict[str, Any]]],
    state: dict[str, Any] | None,
)
```

| Name | Type |
|------|------|
| `id` | `str` |
| `name` | `str` |
| `error` | `NotRequired[str]` |
| `result` | `NotRequired[Any]` |
| `interrupts` | `NotRequired[list[dict[str, Any]]]` |
| `state` | `dict[str, Any] \| None` |


## Properties

- `id`
- `name`
- `error`
- `result`
- `interrupts`
- `state`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/schema.py#L645)