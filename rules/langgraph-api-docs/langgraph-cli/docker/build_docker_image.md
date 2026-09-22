# build_docker_image

> **Function** in `langgraph_cli`

📖 [View in docs](https://reference.langchain.com/python/langgraph-cli/docker/build_docker_image)

Build a Docker image from a LangGraph config.

## Signature

```python
build_docker_image(
    runner,
    set: Callable[[str], None],
    config: pathlib.Path,
    config_json: dict,
    base_image: str | None,
    api_version: str | None,
    pull: bool,
    tag: str,
    passthrough: Sequence[str] = (),
    install_command: str | None = None,
    build_command: str | None = None,
    docker_command: Sequence[str] | None = None,
    extra_flags: Sequence[str] = (),
    verbose: bool = True,
)
```

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/1a9baae9592e0c21336f6e09c891ba75481fd657/libs/cli/langgraph_cli/docker.py#L333)