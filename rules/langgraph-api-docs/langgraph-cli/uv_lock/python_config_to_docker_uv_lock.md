# python_config_to_docker_uv_lock

> **Function** in `langgraph_cli`

📖 [View in docs](https://reference.langchain.com/python/langgraph-cli/uv_lock/python_config_to_docker_uv_lock)

## Signature

```python
python_config_to_docker_uv_lock(
    config_path: pathlib.Path,
    config: Config,
    base_image: str,
    api_version: str | None = None,
    *,
    build_tools_to_uninstall: tuple[str, ...] | None,
) -> tuple[str, dict[str, str]]
```

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/1a9baae9592e0c21336f6e09c891ba75481fd657/libs/cli/langgraph_cli/uv_lock.py#L868)