# AsyncGraphRunStream

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/stream/run_stream/AsyncGraphRunStream)

Async run stream with caller-driven pumping.

Async iteration on any projection drives the graph forward — there
is no background task. Concurrent consumers share a single-flight
pump via an `asyncio.Lock`, so each awaiting cursor contributes one
event per acquisition. Backpressure comes from the logs: when a
subscribed log's buffer reaches `maxlen`, `apush` awaits the
subscriber to drain, which holds back the pump and paces the graph.

Projections are single-consumer — a second `aiter(run.values)`
raises. Use `projection.tee(n)` for fan-out.

Use as an async context manager to guarantee clean shutdown on
early exit:

```python
async with await handler.astream(input) as run:
    async for msg in run.messages:
        ...
```

!!! warning

    Awaited from `Pregel.astream_events(version="v3")`, which is
    experimental and may change.

## Signature

```python
AsyncGraphRunStream(
    self,
    graph_aiter: AsyncIterator[Any] | None,
    mux: StreamMux,
    *,
    wire_pump: bool = True,
)
```

## Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `graph_aiter` | `AsyncIterator[Any] \| None` | Yes | Async iterator over the graph's stream, or `None` for nested run streams whose pump is driven by an outer run (e.g. `AsyncSubgraphRunStream`). |
| `mux` | `StreamMux` | Yes | The StreamMux owning projections and the main log. |
| `wire_pump` | `bool` | No | When True (default), bind `_apump_next` as the mux's async pump callable. Subclasses that inherit a parent pump via `StreamMux._make_child` should pass False to preserve the parent binding. (default: `True`) |

## Constructors

```python
__init__(
    self,
    graph_aiter: AsyncIterator[Any] | None,
    mux: StreamMux,
    *,
    wire_pump: bool = True,
) -> None
```

| Name | Type |
|------|------|
| `graph_aiter` | `AsyncIterator[Any] \| None` |
| `mux` | `StreamMux` |
| `wire_pump` | `bool` |


## Properties

- `extensions`

## Methods

- [`abort()`](https://reference.langchain.com/python/langgraph/stream/run_stream/AsyncGraphRunStream/abort)
- [`output()`](https://reference.langchain.com/python/langgraph/stream/run_stream/AsyncGraphRunStream/output)
- [`interrupted()`](https://reference.langchain.com/python/langgraph/stream/run_stream/AsyncGraphRunStream/interrupted)
- [`interrupts()`](https://reference.langchain.com/python/langgraph/stream/run_stream/AsyncGraphRunStream/interrupts)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/stream/run_stream.py#L303)