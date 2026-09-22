# on

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/auth/types/on)

Namespace for type definitions of different API operations.

This class organizes type definitions for create, read, update, delete,
and search operations across different resources (threads, assistants, crons).

???+ note "Usage"
    Start by denying all requests by default, then add handlers to allow access:

    ```python
    from langgraph_sdk import Auth

    auth = Auth()

    # Default deny: reject all requests without a specific handler
    @auth.on
    async def deny_all(ctx: Auth.types.AuthContext, value: Auth.on.value):
        return False

    # Allow thread creation, stamping the owner
    @auth.on.threads.create
    async def allow_thread_create(ctx: Auth.types.AuthContext, value: Auth.on.threads.create.value):
        value.setdefault("metadata", {})["owner"] = ctx.user.identity

    # Allow assistant search, scoped to user's resources
    @auth.on.assistants.search
    async def allow_assistant_search(ctx: Auth.types.AuthContext, value: Auth.on.assistants.search.value):
        return {"owner": ctx.user.identity}
    ```

## Signature

```python
on()
```

## Properties

- `value`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/auth/types.py#L976)