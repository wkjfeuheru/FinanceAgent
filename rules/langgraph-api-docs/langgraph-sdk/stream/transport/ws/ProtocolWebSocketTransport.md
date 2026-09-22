# ProtocolWebSocketTransport

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/stream/transport/ws/ProtocolWebSocketTransport)

v3 protocol transport using HTTP commands and WebSocket events.

## Signature

```python
ProtocolWebSocketTransport(
    self,
    *,
    client: httpx.AsyncClient,
    thread_id: str,
    commands_path: str | None = None,
    stream_path: str | None = None,
    headers: Mapping[str, str] | None = None,
    connect: Callable[..., Any] = websocket_connect,
    max_queue_size: int = 1024,
    ping_interval: float | None = 20.0,
    ping_timeout: float | None = 20.0,
)
```

## Constructors

```python
__init__(
    self,
    *,
    client: httpx.AsyncClient,
    thread_id: str,
    commands_path: str | None = None,
    stream_path: str | None = None,
    headers: Mapping[str, str] | None = None,
    connect: Callable[..., Any] = websocket_connect,
    max_queue_size: int = 1024,
    ping_interval: float | None = 20.0,
    ping_timeout: float | None = 20.0,
) -> None
```

| Name | Type |
|------|------|
| `client` | `httpx.AsyncClient` |
| `thread_id` | `str` |
| `commands_path` | `str \| None` |
| `stream_path` | `str \| None` |
| `headers` | `Mapping[str, str] \| None` |
| `connect` | `Callable[..., Any]` |
| `max_queue_size` | `int` |
| `ping_interval` | `float \| None` |
| `ping_timeout` | `float \| None` |


## Properties

- `thread_id`

## Methods

- [`send_command()`](https://reference.langchain.com/python/langgraph-sdk/stream/transport/ws/ProtocolWebSocketTransport/send_command)
- [`open_event_stream()`](https://reference.langchain.com/python/langgraph-sdk/stream/transport/ws/ProtocolWebSocketTransport/open_event_stream)
- [`close()`](https://reference.langchain.com/python/langgraph-sdk/stream/transport/ws/ProtocolWebSocketTransport/close)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/stream/transport/ws.py#L25)