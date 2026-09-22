# get_callback_manager_for_config

> **Function** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/_internal/_config/get_callback_manager_for_config)

Get a callback manager for a config.

## Signature

```python
get_callback_manager_for_config(
    config: RunnableConfig,
    tags: Sequence[str] | None = None,
) -> CallbackManager
```

## Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `config` | `RunnableConfig` | Yes | The config. |

## Returns

`CallbackManager`

The callback manager.

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/_internal/_config.py#L236)