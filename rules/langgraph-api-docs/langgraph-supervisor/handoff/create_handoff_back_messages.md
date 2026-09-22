# create_handoff_back_messages

> **Function** in `langgraph_supervisor`

📖 [View in docs](https://reference.langchain.com/python/langgraph-supervisor/handoff/create_handoff_back_messages)

Create a pair of (AIMessage, ToolMessage) to add to the message history when returning control to the supervisor.

## Signature

```python
create_handoff_back_messages(
    agent_name: str,
    supervisor_name: str,
) -> tuple[AIMessage, ToolMessage]
```

---

[View source on GitHub](https://github.com/langchain-ai/langgraph-supervisor-py/blob/69c808c071e0a420255155c0ef383962b4872003/langgraph_supervisor/handoff.py#L128)