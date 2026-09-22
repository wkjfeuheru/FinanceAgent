# patch_config

> **Function** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/_internal/_config/patch_config)

Patch a config with new values.

## Signature

```python
patch_config(
    config: RunnableConfig | None,
    *,
    callbacks: Callbacks = None,
    recursion_limit: int | None = None,
    max_concurrency: int | None = None,
    run_name: str | None = None,
    configurable: dict[str, Any] | None = None,
) -> RunnableConfig
```

## Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `config` | `RunnableConfig \| None` | Yes | The config to patch. |
| `callbacks` | `Callbacks` | No | The callbacks to set. (default: `None`) |
| `recursion_limit` | `int \| None` | No | The recursion limit to set. (default: `None`) |
| `max_concurrency` | `int \| None` | No | The max number of concurrent steps to run, which also applies to parallelized steps. (default: `None`) |
| `run_name` | `str \| None` | No | The run name to set. (default: `None`) |
| `configurable` | `dict[str, Any] \| None` | No | The configurable to set. (default: `None`) |

## Returns

`RunnableConfig`

The patched config.

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/_internal/_config.py#L194)