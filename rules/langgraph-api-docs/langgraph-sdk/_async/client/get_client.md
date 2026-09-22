# get_client

> **Function** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/_async/client/get_client)

Create and configure a LangGraphClient.

The client provides programmatic access to LangSmith Deployment. It supports
both remote servers and local in-process connections (when running inside a LangGraph server).

## Signature

```python
get_client(
    *,
    url: str | None = None,
    api_key: str | None = NOT_PROVIDED,
    headers: Mapping[str, str] | None = None,
    timeout: TimeoutTypes | None = None,
) -> LangGraphClient
```

## Description

???+ example "Connect to a remote server:"

    ```python
    from langgraph_sdk import get_client

    # get top-level LangGraphClient
    client = get_client(url="http://localhost:8123")

    # example usage: client.<model>.<method_name>()
    assistants = await client.assistants.get(assistant_id="some_uuid")
    ```

???+ example "Connect in-process to a running LangGraph server:"

    ```python
    from langgraph_sdk import get_client

    client = get_client(url=None)

    async def my_node(...):
        subagent_result = await client.runs.wait(
            thread_id=None,
            assistant_id="agent",
            input={"messages": [{"role": "user", "content": "Foo"}]},
        )
    ```

???+ example "Skip auto-loading API key from environment:"

    ```python
    from langgraph_sdk import get_client

    # Don't load API key from environment variables
    client = get_client(
        url="http://localhost:8123",
        api_key=None
    )
    ```

## Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `url` | `str \| None` | No |  Base URL of the LangGraph API. - If `None`, the client first attempts an in-process connection via ASGI transport.   If that fails, it defers registration until after app initialization. This   only works if the client is used from within the Agent server. (default: `None`) |
| `api_key` | `str \| None` | No |  API key for authentication. Can be:   - A string: use this exact API key   - `None`: explicitly skip loading from environment variables   - Not provided (default): auto-load from environment in this order:     1. `LANGGRAPH_API_KEY`     2. `LANGSMITH_API_KEY`     3. `LANGCHAIN_API_KEY` (default: `NOT_PROVIDED`) |
| `headers` | `Mapping[str, str] \| None` | No |  Additional HTTP headers to include in requests. Merged with authentication headers. (default: `None`) |
| `timeout` | `TimeoutTypes \| None` | No |  HTTP timeout configuration. May be:   - `httpx.Timeout` instance   - float (total seconds)   - tuple `(connect, read, write, pool)` in seconds Defaults: connect=5, read=300, write=300, pool=5. (default: `None`) |

## Returns

`LangGraphClient`


A top-level client exposing sub-clients for assistants, threads,
runs, and cron operations.

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/_async/client.py#L29)