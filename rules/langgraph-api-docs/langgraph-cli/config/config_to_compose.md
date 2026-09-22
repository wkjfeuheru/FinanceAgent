# config_to_compose

> **Function** in `langgraph_cli`

📖 [View in docs](https://reference.langchain.com/python/langgraph-cli/config/config_to_compose)

## Signature

```python
config_to_compose(
    config_path: pathlib.Path,
    config: Config,
    base_image: str | None = None,
    api_version: str | None = None,
    image: str | None = None,
    watch: bool = False,
    engine_runtime_mode: str = 'combined_queue_worker',
) -> str
```

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/1a9baae9592e0c21336f6e09c891ba75481fd657/libs/cli/langgraph_cli/config.py#L1651)