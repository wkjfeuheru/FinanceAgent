# ProtocolEvent

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/stream/_types/ProtocolEvent)

A protocol event emitted by the streaming infrastructure.

Wraps a raw stream part (values, messages, custom, etc.) in a uniform
envelope with a monotonic sequence number assigned by the root StreamMux.
Consumers that need a total order across root events should use `seq`, not
`params.timestamp` (which is wall-clock and not monotonic).

## Signature

```python
ProtocolEvent()
```

## Extends

- `TypedDict`

## Constructors

```python
__init__(
    type: Literal['event'],
    event_id: NotRequired[str],
    seq: NotRequired[int],
    method: str,
    params: _ProtocolEventParams,
)
```

| Name | Type |
|------|------|
| `type` | `Literal['event']` |
| `event_id` | `NotRequired[str]` |
| `seq` | `NotRequired[int]` |
| `method` | `str` |
| `params` | `_ProtocolEventParams` |


## Properties

- `type`
- `event_id`
- `seq`
- `method`
- `params`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/stream/_types.py#L28)