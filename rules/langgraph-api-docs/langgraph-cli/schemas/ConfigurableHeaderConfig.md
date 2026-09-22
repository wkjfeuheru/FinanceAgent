# ConfigurableHeaderConfig

> **Class** in `langgraph_cli`

📖 [View in docs](https://reference.langchain.com/python/langgraph-cli/schemas/ConfigurableHeaderConfig)

Customize which headers to include as configurable values in your runs.

By default, omits x-api-key, x-tenant-id, and x-service-key.

Exclusions (if provided) take precedence.

Each value can be a raw string with an optional wildcard.

## Signature

```python
ConfigurableHeaderConfig()
```

## Extends

- `TypedDict`

## Constructors

```python
__init__(
    includes: list[str] | None,
    excludes: list[str] | None,
)
```

| Name | Type |
|------|------|
| `includes` | `list[str] \| None` |
| `excludes` | `list[str] \| None` |


## Properties

- `includes`
- `excludes`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/1a9baae9592e0c21336f6e09c891ba75481fd657/libs/cli/langgraph_cli/schemas.py#L415)