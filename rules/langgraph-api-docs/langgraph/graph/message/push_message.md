# push_message

> **Function** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/graph/message/push_message)

Write a message manually to the `messages` / `messages-tuple` stream mode.

Will automatically write to the channel specified in the `state_key` unless `state_key` is `None`.

## Signature

```python
push_message(
    message: MessageLikeRepresentation | BaseMessageChunk,
    *,
    state_key: str | None = 'messages',
) -> AnyMessage
```

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/graph/message.py#L392)