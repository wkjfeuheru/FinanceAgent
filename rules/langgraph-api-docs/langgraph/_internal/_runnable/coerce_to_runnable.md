# coerce_to_runnable

> **Function** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/_internal/_runnable/coerce_to_runnable)

Coerce a runnable-like object into a Runnable.

## Signature

```python
coerce_to_runnable(
    thing: RunnableLike,
    *,
    name: str | None,
    trace: bool,
) -> Runnable
```

## Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `thing` | `RunnableLike` | Yes | A runnable-like object. |

## Returns

`Runnable`

A Runnable.

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/_internal/_runnable.py#L529)