# remove_inline_agent_name

> **Function** in `langgraph_supervisor`

📖 [View in docs](https://reference.langchain.com/python/langgraph-supervisor/agent_name/remove_inline_agent_name)

Remove explicit name and content XML tags from the AI message content.

Examples:

    >>> remove_inline_agent_name(AIMessage(content="<name>assistant</name><content>Hello</content>", name="assistant"))
    AIMessage(content="Hello", name="assistant")

    >>> remove_inline_agent_name(AIMessage(content=[{"type": "text", "text": "<name>assistant</name><content>Hello</content>"}], name="assistant"))
    AIMessage(content=[{"type": "text", "text": "Hello"}], name="assistant")

## Signature

```python
remove_inline_agent_name(
    message: BaseMessage,
) -> BaseMessage
```

---

[View source on GitHub](https://github.com/langchain-ai/langgraph-supervisor-py/blob/69c808c071e0a420255155c0ef383962b4872003/langgraph_supervisor/agent_name.py#L58)