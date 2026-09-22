# normalize_name

> **Function** in `langgraph_cli`

📖 [View in docs](https://reference.langchain.com/python/langgraph-cli/deploy/normalize_name)

Sanitize a deployment/directory name into a valid deployment name.

LangSmith Deployment names only allow lowercase
alphanumeric characters and hyphens ([a-z0-9-]).
Invalid characters are replaced with hyphens.

## Signature

```python
normalize_name(
    value: str | None,
) -> str
```

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/1a9baae9592e0c21336f6e09c891ba75481fd657/libs/cli/langgraph_cli/deploy.py#L342)