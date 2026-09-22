# HttpConfig

> **Class** in `langgraph_cli`

📖 [View in docs](https://reference.langchain.com/python/langgraph-cli/schemas/HttpConfig)

Configuration for the built-in HTTP server that powers your deployment's routes and endpoints.

## Signature

```python
HttpConfig()
```

## Extends

- `TypedDict`

## Constructors

```python
__init__(
    app: str,
    disable_assistants: bool,
    disable_threads: bool,
    disable_runs: bool,
    disable_store: bool,
    disable_mcp: bool,
    disable_a2a: bool,
    disable_meta: bool,
    disable_ui: bool,
    disable_webhooks: bool,
    cors: CorsConfig | None,
    configurable_headers: ConfigurableHeaderConfig | None,
    logging_headers: ConfigurableHeaderConfig | None,
    middleware_order: MiddlewareOrders | None,
    enable_custom_route_auth: bool,
    mount_prefix: str,
)
```

| Name | Type |
|------|------|
| `app` | `str` |
| `disable_assistants` | `bool` |
| `disable_threads` | `bool` |
| `disable_runs` | `bool` |
| `disable_store` | `bool` |
| `disable_mcp` | `bool` |
| `disable_a2a` | `bool` |
| `disable_meta` | `bool` |
| `disable_ui` | `bool` |
| `disable_webhooks` | `bool` |
| `cors` | `CorsConfig \| None` |
| `configurable_headers` | `ConfigurableHeaderConfig \| None` |
| `logging_headers` | `ConfigurableHeaderConfig \| None` |
| `middleware_order` | `MiddlewareOrders \| None` |
| `enable_custom_route_auth` | `bool` |
| `mount_prefix` | `str` |


## Properties

- `app`
- `disable_assistants`
- `disable_threads`
- `disable_runs`
- `disable_store`
- `disable_mcp`
- `disable_a2a`
- `disable_meta`
- `disable_ui`
- `disable_webhooks`
- `cors`
- `configurable_headers`
- `logging_headers`
- `middleware_order`
- `enable_custom_route_auth`
- `mount_prefix`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/1a9baae9592e0c21336f6e09c891ba75481fd657/libs/cli/langgraph_cli/schemas.py#L442)