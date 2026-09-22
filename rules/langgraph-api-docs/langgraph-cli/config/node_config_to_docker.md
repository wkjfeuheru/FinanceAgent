# node_config_to_docker

> **Function** in `langgraph_cli`

📖 [View in docs](https://reference.langchain.com/python/langgraph-cli/config/node_config_to_docker)

## Signature

```python
node_config_to_docker(
    config_path: pathlib.Path,
    config: Config,
    base_image: str,
    api_version: str | None = None,
    install_command: str | None = None,
    build_command: str | None = None,
    build_context: str | None = None,
) -> tuple[str, dict[str, str]]
```

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/1a9baae9592e0c21336f6e09c891ba75481fd657/libs/cli/langgraph_cli/config.py#L1482)