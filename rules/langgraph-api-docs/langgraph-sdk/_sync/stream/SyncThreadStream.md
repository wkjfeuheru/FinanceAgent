# SyncThreadStream

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/_sync/stream/SyncThreadStream)

Synchronous context manager for one thread's v3 streaming session.

Construct via `client.threads.stream(thread_id=None, *, assistant_id, ...)`
rather than instantiating directly.

## Signature

```python
SyncThreadStream(
    self,
    *,
    http: SyncHttpClient,
    thread_id: str,
    assistant_id: str,
    headers: Mapping[str, str] | None = None,
    run_start_timeout: float | None = None,
    explicit_thread_id: bool = False,
    transport_kind: Literal['sse', 'websocket'] = 'sse',
)
```

## Constructors

```python
__init__(
    self,
    *,
    http: SyncHttpClient,
    thread_id: str,
    assistant_id: str,
    headers: Mapping[str, str] | None = None,
    run_start_timeout: float | None = None,
    explicit_thread_id: bool = False,
    transport_kind: Literal['sse', 'websocket'] = 'sse',
) -> None
```

| Name | Type |
|------|------|
| `http` | `SyncHttpClient` |
| `thread_id` | `str` |
| `assistant_id` | `str` |
| `headers` | `Mapping[str, str] \| None` |
| `run_start_timeout` | `float \| None` |
| `explicit_thread_id` | `bool` |
| `transport_kind` | `Literal['sse', 'websocket']` |


## Properties

- `thread_id`
- `assistant_id`
- `interrupted`
- `interrupts`
- `run`
- `agent`
- `values`
- `messages`
- `tool_calls`
- `subgraphs`
- `subagents`
- `extensions`
- `output`
- `events`

## Methods

- [`close()`](https://reference.langchain.com/python/langgraph-sdk/_sync/stream/SyncThreadStream/close)
- [`subscribe()`](https://reference.langchain.com/python/langgraph-sdk/_sync/stream/SyncThreadStream/subscribe)
- [`interleave_projections()`](https://reference.langchain.com/python/langgraph-sdk/_sync/stream/SyncThreadStream/interleave_projections)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/_sync/stream.py#L1073)