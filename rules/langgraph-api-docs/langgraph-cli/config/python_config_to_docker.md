# python_config_to_docker

> **Function** in `langgraph_cli`

📖 [View in docs](https://reference.langchain.com/python/langgraph-cli/config/python_config_to_docker)

Generate a Dockerfile from the configuration.

## Signature

```python
python_config_to_docker(
    config_path: pathlib.Path,
    config: Config,
    base_image: str,
    api_version: str | None = None,
    *,
    escape_variables: bool = False,
) -> tuple[str, dict[str, str]]
```

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/1a9baae9592e0c21336f6e09c891ba75481fd657/libs/cli/langgraph_cli/config.py#L1263)