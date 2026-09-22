# add_inline_agent_name

> **Function** in `langgraph_supervisor`

📖 [View in docs](https://reference.langchain.com/python/langgraph-supervisor/agent_name/add_inline_agent_name)

Add name and content XML tags to the message content.

Examples:

    >>> add_inline_agent_name(AIMessage(content="Hello", name="assistant"))
    AIMessage(content="<name>assistant</name><content>Hello</content>", name="assistant")

    >>> add_inline_agent_name(AIMessage(content=[{"type": "text", "text": "Hello"}], name="assistant"))
    AIMessage(content=[{"type": "text", "text": "<name>assistant</name><content>Hello</content>"}], name="assistant")

## Signature

```python
add_inline_agent_name(
    message: BaseMessage,
) -> BaseMessage
```

---

[View source on GitHub](https://github.com/langchain-ai/langgraph-supervisor-py/blob/69c808c071e0a420255155c0ef383962b4872003/langgraph_supervisor/agent_name.py#L29)