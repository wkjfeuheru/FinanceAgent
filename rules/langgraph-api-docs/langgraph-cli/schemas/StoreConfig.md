# StoreConfig

> **Class** in `langgraph_cli`

📖 [View in docs](https://reference.langchain.com/python/langgraph-cli/schemas/StoreConfig)

Configuration for the built-in long-term memory store.

This store can optionally perform semantic search. If you omit `index`,
the store will just handle traditional (non-embedded) data without vector lookups.

## Signature

```python
StoreConfig()
```

## Extends

- `TypedDict`

## Constructors

```python
__init__(
    index: IndexConfig | None,
    ttl: TTLConfig | None,
)
```

| Name | Type |
|------|------|
| `index` | `IndexConfig \| None` |
| `ttl` | `TTLConfig \| None` |


## Properties

- `index`
- `ttl`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/1a9baae9592e0c21336f6e09c891ba75481fd657/libs/cli/langgraph_cli/schemas.py#L83)