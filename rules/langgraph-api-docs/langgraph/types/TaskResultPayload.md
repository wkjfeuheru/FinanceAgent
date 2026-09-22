# TaskResultPayload

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/types/TaskResultPayload)

Payload for a task result event.

## Signature

```python
TaskResultPayload()
```

## Extends

- `TypedDict`

## Constructors

```python
__init__(
    id: str,
    name: str,
    error: str | None,
    interrupts: list[dict],
    result: dict[str, Any],
)
```

| Name | Type |
|------|------|
| `id` | `str` |
| `name` | `str` |
| `error` | `str \| None` |
| `interrupts` | `list[dict]` |
| `result` | `dict[str, Any]` |


## Properties

- `id`
- `name`
- `error`
- `interrupts`
- `result`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/types.py#L165)