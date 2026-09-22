# CheckpointPayload

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/types/CheckpointPayload)

Payload for a checkpoint event.

## Signature

```python
CheckpointPayload()
```

## Extends

- `TypedDict`
- `Generic[StateT]`

## Constructors

```python
__init__(
    config: RunnableConfig | None,
    metadata: CheckpointMetadata,
    values: StateT,
    next: list[str],
    parent_config: RunnableConfig | None,
    tasks: list[CheckpointTask],
)
```

| Name | Type |
|------|------|
| `config` | `RunnableConfig \| None` |
| `metadata` | `CheckpointMetadata` |
| `values` | `StateT` |
| `next` | `list[str]` |
| `parent_config` | `RunnableConfig \| None` |
| `tasks` | `list[CheckpointTask]` |


## Properties

- `config`
- `metadata`
- `values`
- `next`
- `parent_config`
- `tasks`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/types.py#L204)