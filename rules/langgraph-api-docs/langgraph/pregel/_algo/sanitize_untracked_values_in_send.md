# sanitize_untracked_values_in_send

> **Function** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/pregel/_algo/sanitize_untracked_values_in_send)

Pop any values belonging to UntrackedValue channels in Send.arg for safe checkpointing.

Send is often called with state to be passed to the dest node, which may contain
UntrackedValues at the top level. Send is not typed and arg may be a nested dict.

## Signature

```python
sanitize_untracked_values_in_send(
    packet: Send,
    channels: Mapping[str, BaseChannel],
) -> Send
```

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/pregel/_algo.py#L1442)