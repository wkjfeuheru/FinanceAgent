# BaseAuthContext

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/auth/types/BaseAuthContext)

Base class for authentication context.

Provides the fundamental authentication information needed for
authorization decisions.

## Signature

```python
BaseAuthContext(
    self,
    permissions: Sequence[str],
    user: BaseUser,
)
```

## Constructors

```python
__init__(
    self,
    permissions: Sequence[str],
    user: BaseUser,
) -> None
```

| Name | Type |
|------|------|
| `permissions` | `Sequence[str]` |
| `user` | `BaseUser` |


## Properties

- `permissions`
- `user`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/auth/types.py#L373)