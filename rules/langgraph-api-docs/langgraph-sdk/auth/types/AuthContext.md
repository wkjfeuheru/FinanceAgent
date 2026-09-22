# AuthContext

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/auth/types/AuthContext)

Complete authentication context with resource and action information.

Extends BaseAuthContext with specific resource and action being accessed,
allowing for fine-grained access control decisions.

## Signature

```python
AuthContext(
    self,
    permissions: Sequence[str],
    user: BaseUser,
    resource: typing.Literal['runs', 'threads', 'crons', 'assistants', 'store'],
    action: typing.Literal['create', 'read', 'update', 'delete', 'search', 'create_run', 'put', 'get', 'list_namespaces'],
)
```

## Extends

- `BaseAuthContext`

## Constructors

```python
__init__(
    self,
    permissions: Sequence[str],
    user: BaseUser,
    resource: typing.Literal['runs', 'threads', 'crons', 'assistants', 'store'],
    action: typing.Literal['create', 'read', 'update', 'delete', 'search', 'create_run', 'put', 'get', 'list_namespaces'],
) -> None
```

| Name | Type |
|------|------|
| `permissions` | `Sequence[str]` |
| `user` | `BaseUser` |
| `resource` | `typing.Literal['runs', 'threads', 'crons', 'assistants', 'store']` |
| `action` | `typing.Literal['create', 'read', 'update', 'delete', 'search', 'create_run', 'put', 'get', 'list_namespaces']` |


## Properties

- `resource`
- `action`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/auth/types.py#L388)