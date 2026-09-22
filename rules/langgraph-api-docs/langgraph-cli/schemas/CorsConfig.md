# CorsConfig

> **Class** in `langgraph_cli`

📖 [View in docs](https://reference.langchain.com/python/langgraph-cli/schemas/CorsConfig)

Specifies Cross-Origin Resource Sharing (CORS) rules for your server.

If omitted, defaults are typically very restrictive (often no cross-origin requests).
Configure carefully if you want to allow usage from browsers hosted on other domains.

## Signature

```python
CorsConfig()
```

## Extends

- `TypedDict`

## Constructors

```python
__init__(
    allow_origins: list[str],
    allow_methods: list[str],
    allow_headers: list[str],
    allow_credentials: bool,
    allow_origin_regex: str,
    expose_headers: list[str],
    max_age: int,
)
```

| Name | Type |
|------|------|
| `allow_origins` | `list[str]` |
| `allow_methods` | `list[str]` |
| `allow_headers` | `list[str]` |
| `allow_credentials` | `bool` |
| `allow_origin_regex` | `str` |
| `expose_headers` | `list[str]` |
| `max_age` | `int` |


## Properties

- `allow_origins`
- `allow_methods`
- `allow_headers`
- `allow_credentials`
- `allow_origin_regex`
- `expose_headers`
- `max_age`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/1a9baae9592e0c21336f6e09c891ba75481fd657/libs/cli/langgraph_cli/schemas.py#L376)