# CheckpointStreamPart

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/types/CheckpointStreamPart)

Stream part emitted for `stream_mode="checkpoints"`.

## Signature

```python
CheckpointStreamPart()
```

## Extends

- `TypedDict`
- `Generic[StateT]`

## Constructors

```python
__init__(
    type: Literal['checkpoints'],
    ns: tuple[str, ...],
    data: CheckpointPayload[StateT],
)
```

| Name | Type |
|------|------|
| `type` | `Literal['checkpoints']` |
| `ns` | `tuple[str, ...]` |
| `data` | `CheckpointPayload[StateT]` |


## Properties

- `type`
- `ns`
- `data`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/types.py#L310)