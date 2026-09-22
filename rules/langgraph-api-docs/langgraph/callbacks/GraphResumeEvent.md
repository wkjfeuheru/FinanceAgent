# GraphResumeEvent

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/callbacks/GraphResumeEvent)

Graph lifecycle event emitted when execution resumes from a checkpoint.

## Signature

```python
GraphResumeEvent(
    self,
    run_id: UUID | None,
    status: GraphLifecycleStatus,
    checkpoint_id: str,
    checkpoint_ns: tuple[str, ...],
)
```

## Constructors

```python
__init__(
    self,
    run_id: UUID | None,
    status: GraphLifecycleStatus,
    checkpoint_id: str,
    checkpoint_ns: tuple[str, ...],
) -> None
```

| Name | Type |
|------|------|
| `run_id` | `UUID \| None` |
| `status` | `GraphLifecycleStatus` |
| `checkpoint_id` | `str` |
| `checkpoint_ns` | `tuple[str, ...]` |


## Properties

- `run_id`
- `status`
- `checkpoint_id`
- `checkpoint_ns`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/callbacks.py#L62)