# CheckpointTask

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/types/CheckpointTask)

A task entry within a `CheckpointPayload`.

The keys present depend on the task's state:

- **Error:** `id`, `name`, `error`, `state`
- **Has result:** `id`, `name`, `result`, `interrupts`, `state`
- **Pending:** `id`, `name`, `interrupts`, `state`

## Signature

```python
CheckpointTask()
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
    interrupts: NotRequired[list[dict]],
    state: StateSnapshot | RunnableConfig | None,
)
```

| Name | Type |
|------|------|
| `id` | `str` |
| `name` | `str` |
| `error` | `NotRequired[str]` |
| `result` | `NotRequired[Any]` |
| `interrupts` | `NotRequired[list[dict]]` |
| `state` | `StateSnapshot \| RunnableConfig \| None` |


## Properties

- `id`
- `name`
- `error`
- `result`
- `interrupts`
- `state`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/types.py#L180)