# ToolCallsDecoder

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/stream/decoders/ToolCallsDecoder)

Yields one tool-call handle per `tool-started` event.

Mirrors the per-event body of `_ToolCallsProjection._tool_calls_iter`
(`_async/stream.py:1168-1217`). The thread register/unregister and the
terminal-error-on-close finally stay at the projection / wrapper layer.

## Signature

```python
ToolCallsDecoder(
    self,
    namespace: list[str],
    handle_factory: Callable[..., Any],
)
```

## Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `namespace` | `list[str]` | Yes | Events whose namespace differs are ignored. |
| `handle_factory` | `Callable[..., Any]` | Yes | Keyword-only `(tool_call_id, name, input, namespace) -> handle`. |

## Constructors

```python
__init__(
    self,
    namespace: list[str],
    handle_factory: Callable[..., Any],
)
```

| Name | Type |
|------|------|
| `namespace` | `list[str]` |
| `handle_factory` | `Callable[..., Any]` |


## Methods

- [`feed()`](https://reference.langchain.com/python/langgraph-sdk/stream/decoders/ToolCallsDecoder/feed)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/stream/decoders.py#L199)