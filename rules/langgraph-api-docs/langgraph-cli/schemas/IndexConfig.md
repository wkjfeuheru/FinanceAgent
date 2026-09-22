# IndexConfig

> **Class** in `langgraph_cli`

📖 [View in docs](https://reference.langchain.com/python/langgraph-cli/schemas/IndexConfig)

Configuration for indexing documents for semantic search in the store.

This governs how text is converted into embeddings and stored for vector-based lookups.

## Signature

```python
IndexConfig()
```

## Extends

- `TypedDict`

## Constructors

```python
__init__(
    dims: int,
    embed: str,
    fields: list[str] | None,
)
```

| Name | Type |
|------|------|
| `dims` | `int` |
| `embed` | `str` |
| `fields` | `list[str] \| None` |


## Properties

- `dims`
- `embed`
- `fields`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/1a9baae9592e0c21336f6e09c891ba75481fd657/libs/cli/langgraph_cli/schemas.py#L33)