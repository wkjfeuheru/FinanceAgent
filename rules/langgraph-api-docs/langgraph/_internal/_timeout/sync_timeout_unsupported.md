# sync_timeout_unsupported

> **Function** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/_internal/_timeout/sync_timeout_unsupported)

Build the canonical error for using `timeout` with a sync target.

## Signature

```python
sync_timeout_unsupported(
    name: str,
    *,
    kind: Literal['Node', 'Task'] = 'Node',
) -> ValueError
```

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/_internal/_timeout.py#L21)