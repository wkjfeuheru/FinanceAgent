# ValuesTransformer

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/stream/transformers/ValuesTransformer)

Capture values events as a drainable stream of state snapshots.

Provides the `run.values` projection. `run.output`,
`run.interrupted` and `run.interrupts` are tracked directly
by the run stream and do not depend on this transformer.

Native transformer — projection keys are exposed as direct
attributes on the run stream (e.g. `run.values`).

Only values events at the run's own level are captured; snapshots
from deeper subgraphs are left in the main event log but excluded
from the projection. "Own level" is defined by `scope`, which
`stream_events(version="v3")` / `astream_events(version="v3")` populate from the caller's
checkpoint namespace so that a nested `stream_events(version="v3")` call still
sees its own root snapshots.

## Signature

```python
ValuesTransformer(
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
- `error`

## Methods

- [`init()`](https://reference.langchain.com/python/langgraph/stream/transformers/ValuesTransformer/init)
- [`process()`](https://reference.langchain.com/python/langgraph/stream/transformers/ValuesTransformer/process)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/stream/transformers.py#L28)