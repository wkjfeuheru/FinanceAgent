# GraphRunStream

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/stream/run_stream/GraphRunStream)

Sync run stream with caller-driven pumping.

The caller's iteration on any projection (`values`, `messages`,
raw events, or `output`) drives the graph forward. No background
thread is used — the caller's `for` loop is the pump.

Projections are single-consumer — iterating `run.values` twice
raises. Use `projection.tee(n)` if you genuinely need fan-out.

All transformer projections live in `extensions`. Native transformer
projections (those with `_native = True`) are also set as direct
attributes on this instance (e.g. `run.values`, `run.messages`).

!!! warning

    Returned by `Pregel.stream_events(version="v3")`, which is
    experimental and may change.

## Signature

```python
GraphRunStream(
    self,
    graph_iter: Iterator[Any] | None,
    mux: StreamMux,
    *,
    wire_pump: bool = True,
)
```

## Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `graph_iter` | `Iterator[Any] \| None` | Yes | Pull-based iterator over the graph's stream, or `None` for nested run streams whose pump is driven by an outer run (e.g. `SubgraphRunStream`). |
| `mux` | `StreamMux` | Yes | The StreamMux owning projections and the main log. |
| `wire_pump` | `bool` | No | When True (default), bind `_pump_next` as the mux's pump callable. Subclasses that inherit a parent pump via `StreamMux._make_child` should pass False to preserve the parent binding. (default: `True`) |

## Constructors

```python
__init__(
    self,
    graph_iter: Iterator[Any] | None,
    mux: StreamMux,
    *,
    wire_pump: bool = True,
) -> None
```

| Name | Type |
|------|------|
| `graph_iter` | `Iterator[Any] \| None` |
| `mux` | `StreamMux` |
| `wire_pump` | `bool` |


## Properties

- `extensions`
- `output`
- `interrupted`
- `interrupts`

## Methods

- [`abort()`](https://reference.langchain.com/python/langgraph/stream/run_stream/GraphRunStream/abort)
- [`interleave()`](https://reference.langchain.com/python/langgraph/stream/run_stream/GraphRunStream/interleave)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/stream/run_stream.py#L30)