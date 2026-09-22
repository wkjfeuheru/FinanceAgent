# StreamChannel

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/stream/stream_channel/StreamChannel)

Single-consumer drainable queue for streaming events, with optional
protocol auto-forwarding.

When constructed with a `name`, the StreamMux auto-wires every
`push()` to also inject a `ProtocolEvent` into the main event stream
using the channel's name as the method. When constructed without a
name, the channel is local-only — items are only visible to
in-process consumers that iterate the channel directly.

Items are popped off the front as the consumer advances — there is
no retention beyond what's currently queued. A channel accepts
exactly one subscriber; a second `__iter__` / `__aiter__` call
raises. Use `tee(n)` / `atee(n)` for fan-out.

Starts unbound — neither `__iter__` nor `__aiter__` is available
until the StreamMux calls `_bind(is_async)`. After binding, only
the matching iteration protocol works; the other raises `TypeError`.

Pump wiring (set by the run stream, not by `_bind`):
    - `_request_more`: sync pump callable, returns True if a new
      event was produced.
    - `_arequest_more`: async pump coroutine factory, same contract.

Memory is bounded by caller pace: both sync and async use caller-
driven pumps, so each cursor advance produces at most one event.

Lazy-subscribe: `push` appends to the local buffer only when a
subscriber has registered. Auto-forward via `_wire_fn` always fires
regardless of subscription state.

Lifecycle (`close` / `fail`) is managed by the mux — transformers
don't need to close their channels manually.

## Signature

```python
StreamChannel(
    self,
    name: str | None = None,
    *,
    maxlen: int | None = None,
)
```

## Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `name` | `str \| None` | No | Optional protocol channel name. When set, the StreamMux wires every `push()` to also inject a `ProtocolEvent` into the main event stream. Surfaced on the wire as `custom:<name>` for user-defined transformers, or as `<name>` for channels owned by a native transformer (`_native = True`). When `None`, the channel is local-only. (default: `None`) |
| `maxlen` | `int \| None` | No | Accepted for forward compatibility; currently unused. The caller-driven pump bounds memory naturally for single-consumer use. (default: `None`) |

## Extends

- `Generic[T]`

## Constructors

```python
__init__(
    self,
    name: str | None = None,
    *,
    maxlen: int | None = None,
) -> None
```

| Name | Type |
|------|------|
| `name` | `str \| None` |
| `maxlen` | `int \| None` |


## Properties

- `name`

## Methods

- [`push()`](https://reference.langchain.com/python/langgraph/stream/stream_channel/StreamChannel/push)
- [`close()`](https://reference.langchain.com/python/langgraph/stream/stream_channel/StreamChannel/close)
- [`fail()`](https://reference.langchain.com/python/langgraph/stream/stream_channel/StreamChannel/fail)
- [`tee()`](https://reference.langchain.com/python/langgraph/stream/stream_channel/StreamChannel/tee)
- [`atee()`](https://reference.langchain.com/python/langgraph/stream/stream_channel/StreamChannel/atee)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/stream/stream_channel.py#L14)