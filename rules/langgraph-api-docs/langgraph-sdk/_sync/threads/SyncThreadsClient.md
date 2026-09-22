# SyncThreadsClient

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/_sync/threads/SyncThreadsClient)

Synchronous client for managing threads in LangGraph.

This class provides methods to create, retrieve, and manage threads,
which represent conversations or stateful interactions.

???+ example "Example"

    ```python
    client = get_sync_client(url="http://localhost:2024")
    thread = client.threads.create(metadata={"user_id": "123"})
    ```

## Signature

```python
SyncThreadsClient(
    self,
    http: SyncHttpClient,
)
```

## Constructors

```python
__init__(
    self,
    http: SyncHttpClient,
) -> None
```

| Name | Type |
|------|------|
| `http` | `SyncHttpClient` |


## Properties

- `http`

## Methods

- [`get()`](https://reference.langchain.com/python/langgraph-sdk/_sync/threads/SyncThreadsClient/get)
- [`create()`](https://reference.langchain.com/python/langgraph-sdk/_sync/threads/SyncThreadsClient/create)
- [`update()`](https://reference.langchain.com/python/langgraph-sdk/_sync/threads/SyncThreadsClient/update)
- [`delete()`](https://reference.langchain.com/python/langgraph-sdk/_sync/threads/SyncThreadsClient/delete)
- [`search()`](https://reference.langchain.com/python/langgraph-sdk/_sync/threads/SyncThreadsClient/search)
- [`count()`](https://reference.langchain.com/python/langgraph-sdk/_sync/threads/SyncThreadsClient/count)
- [`copy()`](https://reference.langchain.com/python/langgraph-sdk/_sync/threads/SyncThreadsClient/copy)
- [`prune()`](https://reference.langchain.com/python/langgraph-sdk/_sync/threads/SyncThreadsClient/prune)
- [`get_state()`](https://reference.langchain.com/python/langgraph-sdk/_sync/threads/SyncThreadsClient/get_state)
- [`update_state()`](https://reference.langchain.com/python/langgraph-sdk/_sync/threads/SyncThreadsClient/update_state)
- [`get_history()`](https://reference.langchain.com/python/langgraph-sdk/_sync/threads/SyncThreadsClient/get_history)
- [`stream()`](https://reference.langchain.com/python/langgraph-sdk/_sync/threads/SyncThreadsClient/stream)
- [`join_stream()`](https://reference.langchain.com/python/langgraph-sdk/_sync/threads/SyncThreadsClient/join_stream)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/_sync/threads.py#L30)