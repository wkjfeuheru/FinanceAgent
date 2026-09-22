# AuthConfig

> **Class** in `langgraph_cli`

📖 [View in docs](https://reference.langchain.com/python/langgraph-cli/schemas/AuthConfig)

Configuration for custom authentication logic and how it integrates into the OpenAPI spec.

## Signature

```python
AuthConfig()
```

## Extends

- `TypedDict`

## Constructors

```python
__init__(
    path: str,
    disable_studio_auth: bool,
    openapi: SecurityConfig,
    cache: CacheConfig,
)
```

| Name | Type |
|------|------|
| `path` | `str` |
| `disable_studio_auth` | `bool` |
| `openapi` | `SecurityConfig` |
| `cache` | `CacheConfig` |


## Properties

- `path`
- `disable_studio_auth`
- `openapi`
- `cache`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/1a9baae9592e0c21336f6e09c891ba75481fd657/libs/cli/langgraph_cli/schemas.py#L308)