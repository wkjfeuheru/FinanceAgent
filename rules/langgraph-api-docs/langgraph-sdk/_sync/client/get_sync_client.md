# get_sync_client

> **Function** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/_sync/client/get_sync_client)

Get a synchronous LangGraphClient instance.

## Signature

```python
get_sync_client(
    *,
    url: str | None = None,
    api_key: str | None = NOT_PROVIDED,
    headers: Mapping[str, str] | None = None,
    timeout: TimeoutTypes | None = None,
) -> SyncLangGraphClient
```

## Description

Returns:
    SyncLangGraphClient: The top-level synchronous client for accessing AssistantsClient,
    ThreadsClient, RunsClient, and CronClient.

???+ example "Example"

    ```python
    from langgraph_sdk import get_sync_client

    # get top-level synchronous LangGraphClient
    client = get_sync_client(url="http://localhost:8123")

    # example usage: client.<model>.<method_name>()
    assistant = client.assistants.get(assistant_id="some_uuid")
    ```

???+ example "Skip auto-loading API key from environment:"

    ```python
    from langgraph_sdk import get_sync_client

    # Don't load API key from environment variables
    client = get_sync_client(
        url="http://localhost:8123",
        api_key=None
    )
    ```

## Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `url` | `str \| None` | No | The URL of the LangGraph API. (default: `None`) |
| `api_key` | `str \| None` | No | API key for authentication. Can be: - A string: use this exact API key - `None`: explicitly skip loading from environment variables - Not provided (default): auto-load from environment in this order:     1. `LANGGRAPH_API_KEY`     2. `LANGSMITH_API_KEY`     3. `LANGCHAIN_API_KEY` (default: `NOT_PROVIDED`) |
| `headers` | `Mapping[str, str] \| None` | No | Optional custom headers (default: `None`) |
| `timeout` | `TimeoutTypes \| None` | No | Optional timeout configuration for the HTTP client. Accepts an httpx.Timeout instance, a float (seconds), or a tuple of timeouts. Tuple format is (connect, read, write, pool) If not provided, defaults to connect=5s, read=300s, write=300s, and pool=5s. (default: `None`) |

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/_sync/client.py#L20)