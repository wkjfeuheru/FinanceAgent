# recast_checkpoint_ns

> **Function** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/_internal/_config/recast_checkpoint_ns)

Remove task IDs from checkpoint namespace.

## Signature

```python
recast_checkpoint_ns(
    ns: str,
) -> str
```

## Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `ns` | `str` | Yes | The checkpoint namespace with task IDs. |

## Returns

`str`

The checkpoint namespace without task IDs.

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/_internal/_config.py#L38)