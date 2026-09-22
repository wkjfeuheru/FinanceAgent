# can_build_locally

> **Function** in `langgraph_cli`

📖 [View in docs](https://reference.langchain.com/python/langgraph-cli/docker/can_build_locally)

Return whether local deployment builds can run on this machine.

Checks:
- Docker binary is installed
- Docker daemon is running
- Buildx is available when cross-compilation is required (non-x86_64)

## Signature

```python
can_build_locally() -> tuple[bool, str | None]
```

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/1a9baae9592e0c21336f6e09c891ba75481fd657/libs/cli/langgraph_cli/docker.py#L52)