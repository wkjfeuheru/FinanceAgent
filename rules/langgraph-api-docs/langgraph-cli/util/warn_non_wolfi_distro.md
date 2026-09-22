# warn_non_wolfi_distro

> **Function** in `langgraph_cli`

📖 [View in docs](https://reference.langchain.com/python/langgraph-cli/util/warn_non_wolfi_distro)

Show warning if image_distro is not set to 'wolfi'.

When ``emit`` is provided, each warning line is sent through it (used by
callers that need JSON-aware output). Otherwise falls back to colored
``click.secho`` output.

## Signature

```python
warn_non_wolfi_distro(
    config_json: dict,
    *,
    emit: Callable[[str], None] | None = None,
) -> None
```

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/1a9baae9592e0c21336f6e09c891ba75481fd657/libs/cli/langgraph_cli/util.py#L12)