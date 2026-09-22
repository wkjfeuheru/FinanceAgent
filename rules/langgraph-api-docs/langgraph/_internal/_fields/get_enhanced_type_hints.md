# get_enhanced_type_hints

> **Function** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/_internal/_fields/get_enhanced_type_hints)

Attempt to extract default values and descriptions from provided type, used for config schema.

## Signature

```python
get_enhanced_type_hints(
    type: type[Any],
) -> Generator[tuple[str, Any, Any, str | None], None, None]
```

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/_internal/_fields.py#L125)