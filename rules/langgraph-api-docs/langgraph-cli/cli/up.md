# up

> **Function** in `langgraph_cli`

📖 [View in docs](https://reference.langchain.com/python/langgraph-cli/cli/up)

## Signature

```python
up(
    config: pathlib.Path,
    docker_compose: pathlib.Path | None,
    port: int,
    recreate: bool,
    pull: bool,
    watch: bool,
    wait: bool,
    verbose: bool,
    debugger_port: int | None,
    debugger_base_url: str | None,
    postgres_uri: str | None,
    api_version: str | None,
    engine_runtime_mode: str,
    image: str | None,
    base_image: str | None,
)
```

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/1a9baae9592e0c21336f6e09c891ba75481fd657/libs/cli/langgraph_cli/cli.py#L245)