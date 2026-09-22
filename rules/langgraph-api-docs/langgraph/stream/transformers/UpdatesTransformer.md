# UpdatesTransformer

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/stream/transformers/UpdatesTransformer)

Capture updates events as a drainable stream of node outputs.

Surfaces `stream_mode="updates"` data on `run.updates` as a
`StreamChannel[dict[str, Any]]`. Each item is a dict mapping a node
(or task) name to the update it returned after a step.

Only events at the run's own scope are captured; updates from deeper
subgraphs are available on the respective subgraph handle's
`.updates` projection.

Native transformer — `run.updates` is a direct attribute.

## Signature

```python
UpdatesTransformer(
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

- [`init()`](https://reference.langchain.com/python/langgraph/stream/transformers/UpdatesTransformer/init)
- [`process()`](https://reference.langchain.com/python/langgraph/stream/transformers/UpdatesTransformer/process)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/stream/transformers.py#L120)