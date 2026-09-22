# WebhookUrlPolicy

> **Class** in `langgraph_cli`

📖 [View in docs](https://reference.langchain.com/python/langgraph-cli/schemas/WebhookUrlPolicy)

## Signature

```python
WebhookUrlPolicy()
```

## Extends

- `TypedDict`

## Constructors

```python
__init__(
    require_https: bool,
    allowed_domains: list[str],
    allowed_ports: list[int],
    max_url_length: int,
    disable_loopback: bool,
)
```

| Name | Type |
|------|------|
| `require_https` | `bool` |
| `allowed_domains` | `list[str]` |
| `allowed_ports` | `list[int]` |
| `max_url_length` | `int` |
| `disable_loopback` | `bool` |


## Properties

- `require_https`
- `allowed_domains`
- `allowed_ports`
- `max_url_length`
- `disable_loopback`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/1a9baae9592e0c21336f6e09c891ba75481fd657/libs/cli/langgraph_cli/schemas.py#L538)