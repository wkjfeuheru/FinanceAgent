# StreamController

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/stream/controller/StreamController)

Manages subscriptions and fan-out against one shared SSE connection.

## Signature

```python
StreamController(
    self,
    *,
    transport: AsyncProtocolTransport,
    run_start_gate: Callable[[], Awaitable[None]] | None = None,
    max_queue_size: int = 1024,
    seen_event_ids_max: int = 10000,
    max_reconnect_attempts: int = 5,
    reconnect_backoff_base: float = 0.1,
    reconnect_backoff_cap: float = 2.0,
)
```

## Description

**Responsibilities:**

- subscription registry (register / unregister)
- shared-stream lifecycle (open on first subscribe, rotate on filter widen)
- dedup of replayed events via a bounded LRU `_SeenEventIds`
- fan-out from the shared stream to per-subscription queues

## Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `transport` | `AsyncProtocolTransport` | Yes | the `AsyncProtocolTransport` bound to this thread session. |
| `run_start_gate` | `Callable[[], Awaitable[None]] \| None` | No | zero-argument async callable that resolves once the current `run.start` has committed server-side (no-op when no run is in flight). (default: `None`) |
| `max_queue_size` | `int` | No | per-subscription queue bound (default 1024). (default: `1024`) |
| `seen_event_ids_max` | `int` | No | LRU cap for the dedup set (default 10_000). (default: `10000`) |

## Constructors

```python
__init__(
    self,
    *,
    transport: AsyncProtocolTransport,
    run_start_gate: Callable[[], Awaitable[None]] | None = None,
    max_queue_size: int = 1024,
    seen_event_ids_max: int = 10000,
    max_reconnect_attempts: int = 5,
    reconnect_backoff_base: float = 0.1,
    reconnect_backoff_cap: float = 2.0,
) -> None
```

| Name | Type |
|------|------|
| `transport` | `AsyncProtocolTransport` |
| `run_start_gate` | `Callable[[], Awaitable[None]] \| None` |
| `max_queue_size` | `int` |
| `seen_event_ids_max` | `int` |
| `max_reconnect_attempts` | `int` |
| `reconnect_backoff_base` | `float` |
| `reconnect_backoff_cap` | `float` |


## Properties

- `register_subscription`
- `unregister_subscription`
- `ensure_fanout_running`

## Methods

- [`subscribe()`](https://reference.langchain.com/python/langgraph-sdk/stream/controller/StreamController/subscribe)
- [`close()`](https://reference.langchain.com/python/langgraph-sdk/stream/controller/StreamController/close)
- [`reconcile_stream()`](https://reference.langchain.com/python/langgraph-sdk/stream/controller/StreamController/reconcile_stream)
- [`observe_applied_through_seq()`](https://reference.langchain.com/python/langgraph-sdk/stream/controller/StreamController/observe_applied_through_seq)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/stream/controller.py#L96)