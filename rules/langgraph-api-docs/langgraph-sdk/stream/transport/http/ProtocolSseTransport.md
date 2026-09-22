# ProtocolSseTransport

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/stream/transport/http/ProtocolSseTransport)

v3 protocol transport bound to a single `thread_id`.

Commands go to `POST /threads/{thread_id}/commands` (JSON in, JSON out).
`open_event_stream` opens filtered SSE streams against
`POST /threads/{thread_id}/stream/events`.

## Signature

```python
ProtocolSseTransport(
    self,
    *,
    client: httpx.AsyncClient,
    thread_id: str,
    commands_path: str | None = None,
    stream_path: str | None = None,
    headers: Mapping[str, str] | None = None,
    max_queue_size: int = 1024,
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
    max_queue_size: int = 1024,
) -> None
```

| Name | Type |
|------|------|
| `client` | `httpx.AsyncClient` |
| `thread_id` | `str` |
| `commands_path` | `str \| None` |
| `stream_path` | `str \| None` |
| `headers` | `Mapping[str, str] \| None` |
| `max_queue_size` | `int` |


## Properties

- `thread_id`

## Methods

- [`send_command()`](https://reference.langchain.com/python/langgraph-sdk/stream/transport/http/ProtocolSseTransport/send_command)
- [`open_event_stream()`](https://reference.langchain.com/python/langgraph-sdk/stream/transport/http/ProtocolSseTransport/open_event_stream)
- [`close()`](https://reference.langchain.com/python/langgraph-sdk/stream/transport/http/ProtocolSseTransport/close)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/stream/transport/http.py#L33)