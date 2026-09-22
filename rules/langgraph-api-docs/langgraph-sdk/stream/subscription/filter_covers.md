# filter_covers

> **Function** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/stream/subscription/filter_covers)

Whether `coverer` is a superset of `target`.

Direct port of `client/stream/index.ts:filterCovers`. Depth coverage
accounts for namespace-prefix offset: a scoped coverer needs enough depth
to absorb the extra levels of any deeper target namespace prefix.

## Signature

```python
filter_covers(
    coverer: dict[str, Any],
    target: dict[str, Any],
) -> bool
```

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/stream/subscription.py#L161)