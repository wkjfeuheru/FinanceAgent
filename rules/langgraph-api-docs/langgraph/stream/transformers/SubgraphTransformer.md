# SubgraphTransformer

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/stream/transformers/SubgraphTransformer)

Discover subgraph invocations as in-process navigation handles.

Per discovered direct-child subgraph, builds a `SubgraphRunStream`
(or `AsyncSubgraphRunStream`) wrapping a child mini-mux scoped to
the subgraph's namespace. Consumers iterate `run.subgraphs` to
receive handles, then drill into `handle.values` / `handle.messages`
/ `handle.subgraphs` (recursive grandchildren) / `handle.lifecycle`.

Each mini-mux owns its own scope and uses its own
`SubgraphTransformer` to discover its direct children, so
grandchildren live on the child handle — never on the root's
`subgraphs` log. Forwarding events into the matching child mini-mux
is what keeps the child's projections populated.

Native transformer — `subgraphs` is exposed as `run.subgraphs`.

## Signature

```python
SubgraphTransformer(
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


## Properties

- `supports_sync`

## Methods

- [`init()`](https://reference.langchain.com/python/langgraph/stream/transformers/SubgraphTransformer/init)
- [`process()`](https://reference.langchain.com/python/langgraph/stream/transformers/SubgraphTransformer/process)
- [`aprocess()`](https://reference.langchain.com/python/langgraph/stream/transformers/SubgraphTransformer/aprocess)
- [`finalize()`](https://reference.langchain.com/python/langgraph/stream/transformers/SubgraphTransformer/finalize)
- [`afinalize()`](https://reference.langchain.com/python/langgraph/stream/transformers/SubgraphTransformer/afinalize)
- [`fail()`](https://reference.langchain.com/python/langgraph/stream/transformers/SubgraphTransformer/fail)
- [`afail()`](https://reference.langchain.com/python/langgraph/stream/transformers/SubgraphTransformer/afail)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/stream/transformers.py#L670)