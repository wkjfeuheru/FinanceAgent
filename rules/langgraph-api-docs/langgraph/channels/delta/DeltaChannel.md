# DeltaChannel

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/channels/delta/DeltaChannel)

Reducer channel that stores only a sentinel in checkpoint blobs and
reconstructs state by replaying ancestor writes through the reducer.

!!! warning "Beta"

    `DeltaChannel` is in beta. The API and on-disk representation may
    change in future releases. Threads written with `DeltaChannel` today
    are expected to remain readable, but the surrounding contract
    (`BaseCheckpointSaver.get_delta_channel_history`, the
    `_DeltaSnapshot` blob shape, the `counters_since_delta_snapshot`
    metadata field) is not yet stable.

The reducer receives the current accumulated value and a batch of writes
in one call: `reducer(state, [write1, write2, ...]) -> new_state`.

Reducers must be deterministic and batching-invariant (associative across
folds): applying two consecutive write batches separately must produce the
same state as applying their concatenation once:

    reducer(reducer(state, xs), ys) == reducer(state, xs + ys)

This lets LangGraph replay checkpointed writes in larger batches than they
were originally produced without changing reconstructed state.

Snapshot cadence is driven by two counters: per-channel update count and
total supersteps since last snapshot. `create_checkpoint` writes a full
`_DeltaSnapshot` blob when EITHER the update count reaches
`snapshot_frequency` OR the supersteps count reaches the system-wide
`DELTA_MAX_SUPERSTEPS_SINCE_SNAPSHOT` bound (default 5000), bounding
replay depth even for channels that stop receiving writes.

## Signature

```python
DeltaChannel(
    self,
    reducer: Callable[[Any, Sequence[Any]], Any],
    typ: type[Value] | None = None,
    *,
    snapshot_frequency: int = 1000,
)
```

## Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `reducer` | `Callable[[Any, Sequence[Any]], Any]` | Yes | `(state, list[writes]) -> new_state`. Must be deterministic and batching-invariant as described above. |
| `typ` | `type[Value] \| None` | No | The value type (e.g. `list`, `dict`). Inferred automatically from the outer type when used inside `Annotated[T, DeltaChannel(...)]`. (default: `None`) |
| `snapshot_frequency` | `int` | No | Every Nth update to this channel writes a snapshot blob (default `1000`). Must be a positive int. (default: `1000`) |

## Extends

- `Generic[Value]`
- `BaseChannel[Any, Any, Any]`

## Constructors

```python
__init__(
    self,
    reducer: Callable[[Any, Sequence[Any]], Any],
    typ: type[Value] | None = None,
    *,
    snapshot_frequency: int = 1000,
) -> None
```

| Name | Type |
|------|------|
| `reducer` | `Callable[[Any, Sequence[Any]], Any]` |
| `typ` | `type[Value] \| None` |
| `snapshot_frequency` | `int` |


## Properties

- `value`
- `reducer`
- `snapshot_frequency`
- `typ`
- `ValueType`
- `UpdateType`

## Methods

- [`copy()`](https://reference.langchain.com/python/langgraph/channels/delta/DeltaChannel/copy)
- [`from_checkpoint()`](https://reference.langchain.com/python/langgraph/channels/delta/DeltaChannel/from_checkpoint)
- [`replay_writes()`](https://reference.langchain.com/python/langgraph/channels/delta/DeltaChannel/replay_writes)
- [`update()`](https://reference.langchain.com/python/langgraph/channels/delta/DeltaChannel/update)
- [`get()`](https://reference.langchain.com/python/langgraph/channels/delta/DeltaChannel/get)
- [`is_available()`](https://reference.langchain.com/python/langgraph/channels/delta/DeltaChannel/is_available)
- [`checkpoint()`](https://reference.langchain.com/python/langgraph/channels/delta/DeltaChannel/checkpoint)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/channels/delta.py#L25)