# normalize_image_tag

> **Function** in `langgraph_cli`

📖 [View in docs](https://reference.langchain.com/python/langgraph-cli/deploy/normalize_image_tag)

Validate and return a Docker image tag.

Tags may only contain [A-Za-z0-9_.-].  Defaults to "latest" when empty.

## Signature

```python
normalize_image_tag(
    value: str,
) -> str
```

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/1a9baae9592e0c21336f6e09c891ba75481fd657/libs/cli/langgraph_cli/deploy.py#L355)