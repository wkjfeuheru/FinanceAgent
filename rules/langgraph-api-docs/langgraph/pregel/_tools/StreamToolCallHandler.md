# StreamToolCallHandler

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/pregel/_tools/StreamToolCallHandler)

Callback handler that emits tool-call lifecycle events on the stream.

Fires on LangChain's `on_tool_*` callbacks and pushes to the `tools`
stream mode. Emits `tool-started` / `tool-output-delta` /
`tool-finished` / `tool-error` payloads keyed by `tool_call_id`.

While a tool is executing, this handler sets `_tool_call_writer` to a
closure bound to that call's namespace and `tool_call_id`.
`ToolRuntime.emit_output_delta` reads that ContextVar so tool bodies
can stream partial output without threading the writer through their
own signature.

Attached by `Pregel.stream` / `astream` when `"tools"` is in
`stream_modes`. `run_inline = True` keeps event ordering
deterministic.

## Signature

```python
StreamToolCallHandler(
    self,
    stream: Callable[[StreamChunk], None],
    subgraphs: bool,
    *,
    parent_ns: tuple[str, ...] | None = None,
)
```

## Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `stream` | `Callable[[StreamChunk], None]` | Yes | Callable that accepts a `StreamChunk` tuple `(namespace, mode, payload)` and enqueues it. |
| `subgraphs` | `bool` | Yes | Whether to emit events from tools called inside nested subgraphs. When False, only tools at the handler's own scope (`parent_ns`) emit. |
| `parent_ns` | `tuple[str, ...] \| None` | No | Namespace where the handler was attached. Mirrors the `StreamMessagesHandler` escape hatch: tools whose containing namespace equals `parent_ns` still emit even with `subgraphs=False`, so a node that explicitly streams a subgraph with `stream_mode="tools"` sees its own tools. (default: `None`) |

## Extends

- `BaseCallbackHandler`
- `_StreamingCallbackHandler`

## Constructors

```python
__init__(
    self,
    stream: Callable[[StreamChunk], None],
    subgraphs: bool,
    *,
    parent_ns: tuple[str, ...] | None = None,
) -> None
```

| Name | Type |
|------|------|
| `stream` | `Callable[[StreamChunk], None]` |
| `subgraphs` | `bool` |
| `parent_ns` | `tuple[str, ...] \| None` |


## Properties

- `run_inline`
- `stream`
- `subgraphs`
- `parent_ns`

## Methods

- [`tap_output_aiter()`](https://reference.langchain.com/python/langgraph/pregel/_tools/StreamToolCallHandler/tap_output_aiter)
- [`tap_output_iter()`](https://reference.langchain.com/python/langgraph/pregel/_tools/StreamToolCallHandler/tap_output_iter)
- [`on_tool_start()`](https://reference.langchain.com/python/langgraph/pregel/_tools/StreamToolCallHandler/on_tool_start)
- [`on_tool_end()`](https://reference.langchain.com/python/langgraph/pregel/_tools/StreamToolCallHandler/on_tool_end)
- [`on_tool_error()`](https://reference.langchain.com/python/langgraph/pregel/_tools/StreamToolCallHandler/on_tool_error)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/pregel/_tools.py#L35)