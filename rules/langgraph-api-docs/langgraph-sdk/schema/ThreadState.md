# ThreadState

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/schema/ThreadState)

Represents the state of a thread.

## Signature

```python
ThreadState()
```

## Extends

- `TypedDict`

## Constructors

```python
__init__(
    values: list[dict] | dict[str, Any],
    next: Sequence[str],
    checkpoint: Checkpoint,
    metadata: Json,
    created_at: str | None,
    parent_checkpoint: Checkpoint | None,
    tasks: Sequence[ThreadTask],
    interrupts: list[Interrupt],
)
```

| Name | Type |
|------|------|
| `values` | `list[dict] \| dict[str, Any]` |
| `next` | `Sequence[str]` |
| `checkpoint` | `Checkpoint` |
| `metadata` | `Json` |
| `created_at` | `str \| None` |
| `parent_checkpoint` | `Checkpoint \| None` |
| `tasks` | `Sequence[ThreadTask]` |
| `interrupts` | `list[Interrupt]` |


## Properties

- `values`
- `next`
- `checkpoint`
- `metadata`
- `created_at`
- `parent_checkpoint`
- `tasks`
- `interrupts`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/schema.py#L333)