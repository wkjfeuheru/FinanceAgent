# prepare

> **Function** in `langgraph_cli`

📖 [View in docs](https://reference.langchain.com/python/langgraph-cli/cli/prepare)

Prepare the arguments and stdin for running the LangGraph API server.

## Signature

```python
prepare(
    runner,
    *,
    capabilities: DockerCapabilities,
    config_path: pathlib.Path,
    docker_compose: pathlib.Path | None,
    port: int,
    pull: bool,
    watch: bool,
    verbose: bool,
    debugger_port: int | None = None,
    debugger_base_url: str | None = None,
    postgres_uri: str | None = None,
    api_version: str | None = None,
    engine_runtime_mode: str = 'combined_queue_worker',
    image: str | None = None,
    base_image: str | None = None,
) -> tuple[list[str], str]
```

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/1a9baae9592e0c21336f6e09c891ba75481fd657/libs/cli/langgraph_cli/cli.py#L982)