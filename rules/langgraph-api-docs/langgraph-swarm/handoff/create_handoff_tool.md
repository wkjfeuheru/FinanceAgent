# create_handoff_tool

> **Function** in `langgraph_swarm`

📖 [View in docs](https://reference.langchain.com/python/langgraph-swarm/handoff/create_handoff_tool)

Create a tool that can handoff control to the requested agent.

## Signature

```python
create_handoff_tool(
    *,
    agent_name: str,
    name: str | None = None,
    description: str | None = None,
) -> BaseTool
```

## Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `agent_name` | `str` | Yes | The name of the agent to handoff control to, i.e. the name of the agent node in the multi-agent graph. Agent names should be simple, clear and unique, preferably in snake_case, although you are only limited to the names accepted by LangGraph nodes as well as the tool names accepted by LLM providers (the tool name will look like this: `transfer_to_<agent_name>`). |
| `name` | `str \| None` | No | Optional name of the tool to use for the handoff. If not provided, the tool name will be `transfer_to_<agent_name>`. (default: `None`) |
| `description` | `str \| None` | No | Optional description for the handoff tool. If not provided, the tool description will be `Ask agent <agent_name> for help`. (default: `None`) |

---

[View source on GitHub](https://github.com/langchain-ai/langgraph-swarm-py/blob/366f9c54f1bc978603e478d2612e57e65e0b0859/langgraph_swarm/handoff.py#L43)