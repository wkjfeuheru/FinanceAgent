# Auth

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/auth/Auth)

Add custom authentication and authorization management to your LangGraph application.

The Auth class provides a unified system for handling authentication and
authorization in LangGraph applications. It supports custom user authentication
protocols and fine-grained authorization rules for different resources and
actions.

To use, create a separate python file and add the path to the file to your
LangGraph API configuration file (`langgraph.json`). Within that file, create
an instance of the Auth class and register authentication and authorization
handlers as needed.

Example `langgraph.json` file:

```json
{
  "dependencies": ["."],
  "graphs": {
    "agent": "./my_agent/agent.py:graph"
  },
  "env": ".env",
  "auth": {
    "path": "./auth.py:my_auth"
  }
```

Then the LangGraph server will load your auth file and run it server-side whenever a request comes in.

???+ example "Basic Usage"

    ```python
    from langgraph_sdk import Auth

    my_auth = Auth()

    @my_auth.authenticate
    async def authenticate(authorization: str) -> Auth.types.MinimalUserDict:
        user = await verify_token(authorization)  # Your token verification logic
        if not user:
            raise Auth.exceptions.HTTPException(
                status_code=401, detail="Unauthorized"
            )
        return {
            "identity": user["id"],
            "permissions": user.get("permissions", []),
        }

    # Default deny: reject all requests that don't have a specific handler
    @my_auth.on
    async def deny_all(ctx: Auth.types.AuthContext, value: Any) -> False:
        return False

    # Allow users to create threads with their own identity as owner
    @my_auth.on.threads.create
    async def allow_thread_create(
        ctx: Auth.types.AuthContext, value: Auth.types.on.threads.create.value
    ):
        metadata = value.setdefault("metadata", {})
        metadata["owner"] = ctx.user.identity

    # Allow users to read and search their own threads
    @my_auth.on.threads.read
    async def allow_thread_read(
        ctx: Auth.types.AuthContext, value: Auth.types.on.threads.read.value
    ) -> Auth.types.FilterType:
        return {"owner": ctx.user.identity}

    @my_auth.on.threads.search
    async def allow_thread_search(
        ctx: Auth.types.AuthContext, value: Auth.types.on.threads.search.value
    ) -> Auth.types.FilterType:
        return {"owner": ctx.user.identity}

    # Scope all store operations to the user's namespace
    @my_auth.on.store
    async def scope_store(ctx: Auth.types.AuthContext, value: Auth.types.on.store.value):
        namespace = tuple(value["namespace"]) if value.get("namespace") else ()
        if not namespace or namespace[0] != ctx.user.identity:
            namespace = (ctx.user.identity, *namespace)
        value["namespace"] = namespace
    ```

???+ note "Request Processing Flow"

    1. Authentication (your `@auth.authenticate` handler) is performed first on **every request**
    2. For authorization, the most specific matching handler is called:
        * If a handler exists for the exact resource and action, it is used (e.g., `@auth.on.threads.create`)
        * Otherwise, if a handler exists for the resource with any action, it is used (e.g., `@auth.on.threads`)
        * Finally, if no specific handlers match, the global handler is used (e.g., `@auth.on`)
        * If no global handler is set, the request is accepted

    This allows you to set default behavior with a global handler while
    overriding specific routes as needed.

## Signature

```python
Auth(
    self,
)
```

## Constructors

```python
__init__(
    self,
) -> None
```


## Properties

- `types`
- `exceptions`
- `on`

## Methods

- [`authenticate()`](https://reference.langchain.com/python/langgraph-sdk/auth/Auth/authenticate)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/auth/__init__.py#L13)