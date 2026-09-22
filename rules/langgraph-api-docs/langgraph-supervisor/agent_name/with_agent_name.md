# with_agent_name

> **Function** in `langgraph_supervisor`

📖 [View in docs](https://reference.langchain.com/python/langgraph-supervisor/agent_name/with_agent_name)

Attach formatted agent names to the messages passed to and from a language model.

This is useful for making a message history with multiple agents more coherent.

## Signature

```python
with_agent_name(
    model: LanguageModelLike,
    agent_name_mode: AgentNameMode,
) -> LanguageModelLike
```

## Description

**agent name is consumed from the message.name field.:**

If you're using an agent built with create_react_agent, name is automatically set.
If you're building a custom agent, make sure to set the name on the AI message returned by the LLM.

## Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `model` | `LanguageModelLike` | Yes | Language model to add agent name formatting to. |
| `agent_name_mode` | `AgentNameMode` | Yes | Use to specify how to expose the agent name to the LLM. - "inline": Add the agent name directly into the content field of the AI message using XML-style tags.     Example: "How can I help you" -> "<name>agent_name</name><content>How can I help you?</content>". |

---

[View source on GitHub](https://github.com/langchain-ai/langgraph-supervisor-py/blob/69c808c071e0a420255155c0ef383962b4872003/langgraph_supervisor/agent_name.py#L100)