# compose_as_dict

> **Function** in `langgraph_cli`

📖 [View in docs](https://reference.langchain.com/python/langgraph-cli/docker/compose_as_dict)

Create a docker compose file as a dictionary in YML style.

## Signature

```python
compose_as_dict(
    capabilities: DockerCapabilities,
    *,
    port: int,
    debugger_port: int | None = None,
    debugger_base_url: str | None = None,
    postgres_uri: str | None = None,
    image: str | None = None,
    base_image: str | None = None,
    api_version: str | None = None,
    engine_runtime_mode: str = 'combined_queue_worker',
) -> dict
```

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/1a9baae9592e0c21336f6e09c891ba75481fd657/libs/cli/langgraph_cli/docker.py#L190)