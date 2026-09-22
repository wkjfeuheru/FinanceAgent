# create_forward_message_tool

> **Function** in `langgraph_supervisor`

📖 [View in docs](https://reference.langchain.com/python/langgraph-supervisor/handoff/create_forward_message_tool)

Create a tool the supervisor can use to forward a worker message by name.

This helps avoid information loss any time the supervisor rewrites a worker query
to the user and also can save some tokens.

## Signature

```python
create_forward_message_tool(
    supervisor_name: str = 'supervisor',
) -> BaseTool
```

## Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `supervisor_name` | `str` | No | The name of the supervisor node (used for namespacing the tool). (default: `'supervisor'`) |

## Returns

`BaseTool`

The 'forward_message' tool.

---

[View source on GitHub](https://github.com/langchain-ai/langgraph-supervisor-py/blob/69c808c071e0a420255155c0ef383962b4872003/langgraph_supervisor/handoff.py#L151)