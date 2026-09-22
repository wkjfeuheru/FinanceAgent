# EncryptionConfig

> **Class** in `langgraph_cli`

📖 [View in docs](https://reference.langchain.com/python/langgraph-cli/schemas/EncryptionConfig)

Configuration for custom at-rest encryption logic.

Allows you to implement custom encryption for sensitive data stored in the database,
including metadata fields and checkpoint blobs.

## Signature

```python
EncryptionConfig()
```

## Extends

- `TypedDict`

## Constructors

```python
__init__(
    path: str,
)
```

| Name | Type |
|------|------|
| `path` | `str` |


## Properties

- `path`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/1a9baae9592e0c21336f6e09c891ba75481fd657/libs/cli/langgraph_cli/schemas.py#L356)