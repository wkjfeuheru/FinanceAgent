# LifecycleTransformer

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/stream/transformers/LifecycleTransformer)

Surface subgraph lifecycle as `lifecycle` protocol events.

Pushes `LifecyclePayload` to a `StreamChannel` named `lifecycle`.
The channel is auto-forwarded by the mux so payloads land in the
main event log under `method = "lifecycle"` (native transformer —
no `custom:` prefix) — visible to remote SDK clients over the
wire and to in-process consumers via `run.lifecycle`.

Tracks subgraphs at every depth strictly below the transformer's
scope, so a graph → subgraph → subgraph chain produces lifecycle
events for both nested levels in a flat stream.

Native transformer — projection key `lifecycle` is exposed as
`run.lifecycle`.

## Signature

```python
LifecycleTransformer(
    self,
    scope: tuple[str, ...] = (),
)
```

## Extends

- `_TasksLifecycleBase`

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


## Methods

- [`init()`](https://reference.langchain.com/python/langgraph/stream/transformers/LifecycleTransformer/init)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/stream/transformers.py#L608)