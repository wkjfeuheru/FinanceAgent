# SecurityConfig

> **Class** in `langgraph_cli`

📖 [View in docs](https://reference.langchain.com/python/langgraph-cli/schemas/SecurityConfig)

Configuration for OpenAPI security definitions and requirements.

Useful for specifying global or path-level authentication and authorization flows
(e.g., OAuth2, API key headers, etc.).

## Signature

```python
SecurityConfig()
```

## Extends

- `TypedDict`

## Constructors

```python
__init__(
    securitySchemes: dict[str, dict[str, Any]],
    security: list[dict[str, list[str]]],
    paths: dict[str, dict[str, list[dict[str, list[str]]]]],
)
```

| Name | Type |
|------|------|
| `securitySchemes` | `dict[str, dict[str, Any]]` |
| `security` | `list[dict[str, list[str]]]` |
| `paths` | `dict[str, dict[str, list[dict[str, list[str]]]]]` |


## Properties

- `securitySchemes`
- `security`
- `paths`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/1a9baae9592e0c21336f6e09c891ba75481fd657/libs/cli/langgraph_cli/schemas.py#L235)