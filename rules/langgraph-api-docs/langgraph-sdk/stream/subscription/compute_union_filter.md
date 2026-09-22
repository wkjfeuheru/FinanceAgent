# compute_union_filter

> **Function** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/stream/subscription/compute_union_filter)

Aggregate a set of subscription filters into one covering filter.

Direct port of `client/stream/index.ts:#computeUnionFilter`.

- Channels are unioned.
- Namespaces: if any subscription omits `namespaces` (wildcard), the union
  is unscoped (omits the key). Otherwise, deduplicated union.
- Depth: if any subscription omits `depth` (unbounded), the union is
  unbounded (omits the key). Otherwise, take the max. `depth=0` is a
  valid bounded value — never omit when all subscriptions provide it.

## Signature

```python
compute_union_filter(
    subscriptions: list[dict[str, Any]],
) -> dict[str, Any]
```

## Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `subscriptions` | `list[dict[str, Any]]` | Yes | list of `SubscribeParams`-shaped dicts. |

## Returns

`dict[str, Any]`

A `SubscribeParams`-shaped dict covering every input.

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/stream/subscription.py#L107)