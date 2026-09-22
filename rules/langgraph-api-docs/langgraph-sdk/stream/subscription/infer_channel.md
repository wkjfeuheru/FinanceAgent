# infer_channel

> **Function** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/stream/subscription/infer_channel)

Map a protocol event's `method` to its subscription channel.

Returns `None` for unrecognized methods so new server-side channels (e.g.
from extension transformers) don't break existing clients.

## Signature

```python
infer_channel(
    event: Event,
) -> Channel | None
```

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/stream/subscription.py#L68)