# TaskResultPayload

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/schema/TaskResultPayload)

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
    interrupts: list[dict[str, Any]],
    result: dict[str, Any],
)
```

| Name | Type |
|------|------|
| `id` | `str` |
| `name` | `str` |
| `error` | `str \| None` |
| `interrupts` | `list[dict[str, Any]]` |
| `result` | `dict[str, Any]` |


## Properties

- `id`
- `name`
- `error`
- `interrupts`
- `result`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/schema.py#L630)