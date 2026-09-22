# build

> **Function** in `langgraph_cli`

📖 [View in docs](https://reference.langchain.com/python/langgraph-cli/cli/build)

## Signature

```python
build(
    config: pathlib.Path,
    docker_build_args: Sequence[str],
    base_image: str | None,
    api_version: str | None,
    engine_runtime_mode: str,
    pull: bool,
    tag: str,
    install_command: str | None,
    build_command: str | None,
)
```

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/1a9baae9592e0c21336f6e09c891ba75481fd657/libs/cli/langgraph_cli/cli.py#L380)