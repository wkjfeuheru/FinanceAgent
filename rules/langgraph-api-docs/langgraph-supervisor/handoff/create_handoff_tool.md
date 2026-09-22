# create_handoff_tool

> **Function** in `langgraph_supervisor`

📖 [View in docs](https://reference.langchain.com/python/langgraph-supervisor/handoff/create_handoff_tool)

Create a tool that can handoff control to the requested agent.

## Signature

```python
create_handoff_tool(
    *,
    agent_name: str,
    name: str | None = None,
    description: str | None = None,
    add_handoff_messages: bool = True,
) -> BaseTool
```

## Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `agent_name` | `str` | Yes | The name of the agent to handoff control to, i.e. the name of the agent node in the multi-agent graph. Agent names should be simple, clear and unique, preferably in snake_case, although you are only limited to the names accepted by LangGraph nodes as well as the tool names accepted by LLM providers (the tool name will look like this: `transfer_to_<agent_name>`). |
| `name` | `str \| None` | No | Optional name of the tool to use for the handoff. If not provided, the tool name will be `transfer_to_<agent_name>`. (default: `None`) |
| `description` | `str \| None` | No | Optional description for the handoff tool. If not provided, the description will be `Ask agent <agent_name> for help`. (default: `None`) |
| `add_handoff_messages` | `bool` | No | Whether to add handoff messages to the message history. If `False`, the handoff messages will be omitted from the message history. (default: `True`) |

---

[View source on GitHub](https://github.com/langchain-ai/langgraph-supervisor-py/blob/69c808c071e0a420255155c0ef383962b4872003/langgraph_supervisor/handoff.py#L55)