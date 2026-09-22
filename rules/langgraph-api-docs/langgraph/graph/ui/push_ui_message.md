# push_ui_message

> **Function** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/graph/ui/push_ui_message)

Push a new UI message to update the UI state.

This function creates and sends a UI message that will be rendered in the UI.
It also updates the graph state with the new UI message.

## Signature

```python
push_ui_message(
    name: str,
    props: dict[str, Any],
    *,
    id: str | None = None,
    metadata: dict[str, Any] | None = None,
    message: AnyMessage | None = None,
    state_key: str | None = 'ui',
    merge: bool = False,
) -> UIMessage
```

## Description

**Example:**

```python
push_ui_message(
    name="component-name",
    props={"content": "Hello world"},
)
```

## Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `name` | `str` | Yes | Name of the UI component to render. |
| `props` | `dict[str, Any]` | Yes | Properties to pass to the UI component. |
| `id` | `str \| None` | No | Optional unique identifier for the UI message. If not provided, a random UUID will be generated. (default: `None`) |
| `metadata` | `dict[str, Any] \| None` | No | Optional additional metadata about the UI message. (default: `None`) |
| `message` | `AnyMessage \| None` | No | Optional message object to associate with the UI message. (default: `None`) |
| `state_key` | `str \| None` | No | Key in the graph state where the UI messages are stored. (default: `'ui'`) |
| `merge` | `bool` | No | Whether to merge props with existing UI message (True) or replace them (False). (default: `False`) |

## Returns

`UIMessage`

The created UI message.

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/graph/ui.py#L61)