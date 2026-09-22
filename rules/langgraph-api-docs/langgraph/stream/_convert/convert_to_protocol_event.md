# convert_to_protocol_event

> **Function** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/stream/_convert/convert_to_protocol_event)

Convert a v2 StreamPart to a ProtocolEvent.

## Signature

```python
convert_to_protocol_event(
    part: StreamPart,
) -> ProtocolEvent
```

## Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `part` | `StreamPart` | Yes | A stream part with keys `type`, `ns`, `data`, and optionally `interrupts` (present on values events). |

## Returns

`ProtocolEvent`

The equivalent ProtocolEvent.

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/stream/_convert.py#L10)