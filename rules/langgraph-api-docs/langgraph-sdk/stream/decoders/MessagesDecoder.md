# MessagesDecoder

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/stream/decoders/MessagesDecoder)

Yields one chat-model stream per `message-start` event.

Subsequent events route to the matching stream via `stream.dispatch(data)`.
Mirrors the per-event body of `_MessagesProjection._messages_iter`
(`_async/stream.py:404-458`). The subscription open/close and the
`_root_messages_inbox` drain branch stay at the projection layer.

## Signature

```python
MessagesDecoder(
    self,
    namespace: list[str],
    stream_factory: Callable[..., Any],
)
```

## Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `namespace` | `list[str]` | Yes | Events whose namespace differs are ignored (scope filter). |
| `stream_factory` | `Callable[..., Any]` | Yes | Keyword-only `(namespace, node, message_id) -> stream`. Sync binds `ChatModelStream`; async binds `AsyncChatModelStream`. |

## Constructors

```python
__init__(
    self,
    namespace: list[str],
    stream_factory: Callable[..., Any],
)
```

| Name | Type |
|------|------|
| `namespace` | `list[str]` |
| `stream_factory` | `Callable[..., Any]` |


## Methods

- [`feed()`](https://reference.langchain.com/python/langgraph-sdk/stream/decoders/MessagesDecoder/feed)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/stream/decoders.py#L139)