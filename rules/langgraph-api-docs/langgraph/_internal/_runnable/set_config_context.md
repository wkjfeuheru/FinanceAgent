# set_config_context

> **Function** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/_internal/_runnable/set_config_context)

Set the child Runnable config + tracing context.

## Signature

```python
set_config_context(
    config: RunnableConfig,
    run: Any = None,
) -> Generator[Context, None, None]
```

## Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `config` | `RunnableConfig` | Yes | The config to set. |

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/_internal/_runnable.py#L105)