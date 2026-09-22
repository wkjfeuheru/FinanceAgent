# ReplayState

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/_internal/_replay/ReplayState)

Tracks which subgraphs have already loaded their pre-replay checkpoint.

During a parent replay, each subgraph's first invocation should restore the
checkpoint from before the replay point. Subsequent invocations of the same
subgraph (e.g. in a loop) should use normal checkpoint loading so they pick
up freshly created checkpoints.

The single `ReplayState` instance is shared by reference across all derived
configs within one parent execution.

## Signature

```python
ReplayState(
    self,
    checkpoint_id: str,
)
```

## Constructors

```python
__init__(
    self,
    checkpoint_id: str,
) -> None
```

| Name | Type |
|------|------|
| `checkpoint_id` | `str` |


## Properties

- `checkpoint_id`

## Methods

- [`get_checkpoint()`](https://reference.langchain.com/python/langgraph/_internal/_replay/ReplayState/get_checkpoint)
- [`aget_checkpoint()`](https://reference.langchain.com/python/langgraph/_internal/_replay/ReplayState/aget_checkpoint)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/_internal/_replay.py#L14)