# MinimalUserDict

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/auth/types/MinimalUserDict)

The dictionary representation of a user.

## Signature

```python
MinimalUserDict()
```

## Extends

- `typing.TypedDict`

## Constructors

```python
__init__(
    identity: typing_extensions.Required[str],
    display_name: str,
    is_authenticated: bool,
    permissions: Sequence[str],
)
```

| Name | Type |
|------|------|
| `identity` | `typing_extensions.Required[str]` |
| `display_name` | `str` |
| `is_authenticated` | `bool` |
| `permissions` | `Sequence[str]` |


## Properties

- `identity`
- `display_name`
- `is_authenticated`
- `permissions`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/auth/types.py#L164)