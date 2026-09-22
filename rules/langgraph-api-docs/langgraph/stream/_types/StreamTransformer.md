# StreamTransformer

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/stream/_types/StreamTransformer)

Extension point for custom stream projections.

Transformers observe protocol events flowing through the StreamMux and
build typed derived projections (StreamChannels, promises, etc.).

Set `_native = True` on a transformer to have its projection keys
exposed as direct attributes on the run stream (in addition to
appearing in `run.extensions`).

Subclasses must implement `init` and override at least one of
`process` / `aprocess`. The `finalize` / `afinalize` and `fail` /
`afail` hooks are optional — the default implementations are no-ops.
StreamChannel instances in the projection dict are auto-closed /
auto-failed by the mux, so most transformers don't need `finalize`
or `fail` at all.

Transformers that need async work pick the async lane by:

1. Overriding `aprocess` (and optionally `afinalize` / `afail`), or
2. Calling `self.schedule(coro)` from inside a sync `process`, or
3. Setting `requires_async = True` explicitly.

The mux detects these cases at registration and raises if they're
used under sync `stream()` — they only work under `astream()`.

Use `aprocess` when the pump must wait for async work before the
next transformer sees the event (e.g. PII redaction that mutates
`event` in place). Use `schedule()` for decoupled async work whose
result lands on an independent projection (e.g. async moderation
scoring, cost lookup, external tracing).

## Signature

```python
StreamTransformer(
    self,
    scope: tuple[str, ...] = (),
)
```

## Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `scope` | `tuple[str, ...]` | No | The namespace tuple the owning mux is scoped to. `()` for the root. Factories receive this at construction time (`factory(scope)` in `StreamMux`). (default: `()`) |

## Extends

- `ABC`

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

- `requires_async`
- `supports_sync`
- `required_stream_modes`
- `before_builtins`
- `scope`

## Methods

- [`init()`](https://reference.langchain.com/python/langgraph/stream/_types/StreamTransformer/init)
- [`process()`](https://reference.langchain.com/python/langgraph/stream/_types/StreamTransformer/process)
- [`aprocess()`](https://reference.langchain.com/python/langgraph/stream/_types/StreamTransformer/aprocess)
- [`finalize()`](https://reference.langchain.com/python/langgraph/stream/_types/StreamTransformer/finalize)
- [`afinalize()`](https://reference.langchain.com/python/langgraph/stream/_types/StreamTransformer/afinalize)
- [`fail()`](https://reference.langchain.com/python/langgraph/stream/_types/StreamTransformer/fail)
- [`afail()`](https://reference.langchain.com/python/langgraph/stream/_types/StreamTransformer/afail)
- [`schedule()`](https://reference.langchain.com/python/langgraph/stream/_types/StreamTransformer/schedule)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/stream/_types.py#L44)