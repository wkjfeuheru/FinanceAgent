# is_prefix_match

> **Function** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/stream/subscription/is_prefix_match)

Whether `event_namespace` starts with `prefix`.

Segments compare literally first; if the prefix segment contains no `:`,
the candidate is also compared after its dynamic suffix is stripped.
Mirrors `is_prefix_match` in `api/langgraph_api/protocol/namespace.py`.

## Signature

```python
is_prefix_match(
    event_namespace: Namespace,
    prefix: Namespace,
) -> bool
```

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/stream/subscription.py#L19)