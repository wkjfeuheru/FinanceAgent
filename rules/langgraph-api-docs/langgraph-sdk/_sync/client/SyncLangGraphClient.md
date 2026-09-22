# SyncLangGraphClient

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/_sync/client/SyncLangGraphClient)

Synchronous client for interacting with the LangGraph API.

This class provides synchronous access to LangGraph API endpoints for managing
assistants, threads, runs, cron jobs, and data storage.

???+ example "Example"

    ```python
    client = get_sync_client(url="http://localhost:2024")
    assistant = client.assistants.get("asst_123")
    ```

## Signature

```python
SyncLangGraphClient(
    self,
    client: httpx.Client,
)
```

## Constructors

```python
__init__(
    self,
    client: httpx.Client,
) -> None
```

| Name | Type |
|------|------|
| `client` | `httpx.Client` |


## Properties

- `http`
- `assistants`
- `threads`
- `runs`
- `crons`
- `store`

## Methods

- [`close()`](https://reference.langchain.com/python/langgraph-sdk/_sync/client/SyncLangGraphClient/close)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/_sync/client.py#L89)