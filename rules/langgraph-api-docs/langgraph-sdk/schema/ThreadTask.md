# ThreadTask

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/schema/ThreadTask)

Represents a task within a thread.

## Signature

```python
ThreadTask()
```

## Extends

- `TypedDict`

## Constructors

```python
__init__(
    id: str,
    name: str,
    error: str | None,
    interrupts: list[Interrupt],
    checkpoint: Checkpoint | None,
    state: ThreadState | None,
    result: dict[str, Any] | None,
)
```

| Name | Type |
|------|------|
| `id` | `str` |
| `name` | `str` |
| `error` | `str \| None` |
| `interrupts` | `list[Interrupt]` |
| `checkpoint` | `Checkpoint \| None` |
| `state` | `ThreadState \| None` |
| `result` | `dict[str, Any] \| None` |


## Properties

- `id`
- `name`
- `error`
- `interrupts`
- `checkpoint`
- `state`
- `result`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/schema.py#L321)