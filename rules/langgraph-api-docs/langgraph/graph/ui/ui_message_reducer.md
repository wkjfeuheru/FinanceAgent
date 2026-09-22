# ui_message_reducer

> **Function** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/graph/ui/ui_message_reducer)

Merge two lists of UI messages, supporting removing UI messages.

This function combines two lists of UI messages, handling both regular UI messages
and `remove-ui` messages. When a `remove-ui` message is encountered, it removes any
UI message with the matching ID from the current state.

## Signature

```python
ui_message_reducer(
    left: list[AnyUIMessage] | AnyUIMessage,
    right: list[AnyUIMessage] | AnyUIMessage,
) -> list[AnyUIMessage]
```

## Description

**Example:**

```python
messages = ui_message_reducer(
    [{"type": "ui", "id": "1", "name": "Chat", "props": {}}],
    {"type": "remove-ui", "id": "1"},
)
```

## Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `left` | `list[AnyUIMessage] \| AnyUIMessage` | Yes | First list of UI messages or single UI message. |
| `right` | `list[AnyUIMessage] \| AnyUIMessage` | Yes | Second list of UI messages or single UI message. |

## Returns

`list[AnyUIMessage]`

Combined list of UI messages with removals applied.

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/graph/ui.py#L165)