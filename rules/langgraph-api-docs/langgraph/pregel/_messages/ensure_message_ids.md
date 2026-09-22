# ensure_message_ids

> **Function** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/pregel/_messages/ensure_message_ids)

Coerce message-like write values to typed BaseMessages with stable IDs.

Called in put_writes() before DeltaChannel writes are submitted to the
checkpointer. Without this the checkpoint may store raw dicts or id=None
BaseMessages; every get_state() replay then produces a different UUID and
the same message appears with a different ID in each LangSmith trace.

Handles three input shapes:
- BaseMessage objects: assign a UUID if id is None.
- Dicts with a known "role" (OpenAI-style) or "type" (LangChain format) at
  the root level: stamp "id" into the dict in-place. The reducer's
  convert_to_messages call will forward the id to the resulting BaseMessage.
- Lists of the above: apply the same logic to each element, replacing dict
  items with coerced BaseMessages so the shared list reference seen by
  checkpoint_pending_writes and the background thread both get typed messages.

Mutating synchronously here (before the background thread is submitted) is
safe: the serialised bytes always reflect the post-coercion state.

## Signature

```python
ensure_message_ids(
    value: Any,
) -> None
```

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/pregel/_messages.py#L426)