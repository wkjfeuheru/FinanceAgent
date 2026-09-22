# CheckpointsTransformer

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/stream/transformers/CheckpointsTransformer)

Capture checkpoint events as a drainable stream.

Surfaces `stream_mode="checkpoints"` data on `run.checkpoints` as
a `StreamChannel[dict[str, Any]]`. Each item is in the same format
as returned by `get_state()`.

Checkpoint events are only emitted when a checkpointer is configured
on the graph. When no checkpointer is present, the projection exists
but receives no events.

Only events at the run's own scope are captured; checkpoint data from
deeper subgraphs is available on the respective subgraph handle's
`.checkpoints` projection.

Native transformer — `run.checkpoints` is a direct attribute.

## Signature

```python
CheckpointsTransformer(
    self,
    scope: tuple[str, ...] = (),
)
```

## Extends

- `StreamTransformer`

## Constructors

```python
__init__(
    self,
    scope: tuple[str, ...] = (),
) -> None
```

| Name | Type |
|------|------|
| `scope` | `tuple[str, ...]` |


## Properties

- `required_stream_modes`

## Methods

- [`init()`](https://reference.langchain.com/python/langgraph/stream/transformers/CheckpointsTransformer/init)
- [`process()`](https://reference.langchain.com/python/langgraph/stream/transformers/CheckpointsTransformer/process)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/stream/transformers.py#L927)