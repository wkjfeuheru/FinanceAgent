# get_runtime

> **Function** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/runtime/get_runtime)

Get the runtime for the current graph run.

## Signature

```python
get_runtime(
    context_schema: type[ContextT] | None = None,
) -> Runtime[ContextT]
```

## Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `context_schema` | `type[ContextT] \| None` | No | Optional schema used for type hinting the return type of the runtime. (default: `None`) |

## Returns

`Runtime[ContextT]`

The runtime for the current graph run.

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/runtime.py#L296)