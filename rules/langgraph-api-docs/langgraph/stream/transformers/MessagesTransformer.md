# MessagesTransformer

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/stream/transformers/MessagesTransformer)

Capture messages events as ChatModelStream objects.

The messages projection yields one `ChatModelStream` (or
`AsyncChatModelStream`) per LLM call. Consumers iterate
`run.messages` to get stream handles, then use each handle's typed
projections (`.text`, `.reasoning`, `.tool_calls`, `.usage`,
`.output`) for per-message content.

Two input shapes are handled (via `params["data"] = (payload,
metadata)` from `StreamMessagesHandler`):

1. Protocol event (dict with `"event"` key) — emitted by
   `stream_events(version="v3")` / `astream_events(version="v3")` via the `on_stream_event`
   callback. Routed to an existing `ChatModelStream` by
   `metadata["run_id"]`. A `message-start` event creates a new
   stream; `message-finish` closes it.
2. Whole `AIMessage` — emitted from `on_chain_end` when a node
   returns a finalized message. Replayed as a synthetic protocol
   event lifecycle via `message_to_events`, then the
   already-complete stream is pushed to the log.

V1 `AIMessageChunk` tuples (from `on_llm_new_token`) are not
streamed into this projection: chat models that want to populate
`run.messages` with content-block streaming must use
`stream_events(version="v3")` / `astream_events(version="v3")`. Models called via the legacy
`stream()` method still surface their final `AIMessage` via
`on_chain_end` when a node returns it as state.

Only events at the run's own level are projected; tokens from
deeper subgraphs are left in the main event log but excluded from
`.messages`. "Own level" is defined by `scope`, which
`stream_events(version="v3")` / `astream_events(version="v3")` populate from the caller's checkpoint
namespace so that a `stream_events(version="v3")` call inside a node still sees its
own root chat model streams on `.messages`. Consumers that need
subgraph tokens should iterate the raw event stream or register a
custom transformer.

Native transformer — the `messages` projection is exposed as a
direct attribute on the run stream.

## Signature

```python
MessagesTransformer(
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

- [`init()`](https://reference.langchain.com/python/langgraph/stream/transformers/MessagesTransformer/init)
- [`process()`](https://reference.langchain.com/python/langgraph/stream/transformers/MessagesTransformer/process)
- [`finalize()`](https://reference.langchain.com/python/langgraph/stream/transformers/MessagesTransformer/finalize)
- [`fail()`](https://reference.langchain.com/python/langgraph/stream/transformers/MessagesTransformer/fail)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/stream/transformers.py#L155)