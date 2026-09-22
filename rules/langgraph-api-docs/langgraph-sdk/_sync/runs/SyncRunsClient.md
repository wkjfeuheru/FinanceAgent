# SyncRunsClient

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/_sync/runs/SyncRunsClient)

Synchronous client for managing runs in LangGraph.

This class provides methods to create, retrieve, and manage runs, which represent
individual executions of graphs.

???+ example "Example"

    ```python
    client = get_sync_client(url="http://localhost:2024")
    run = client.runs.create(thread_id="thread_123", assistant_id="asst_456")
    ```

## Signature

```python
SyncRunsClient(
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

- [`stream()`](https://reference.langchain.com/python/langgraph-sdk/_sync/runs/SyncRunsClient/stream)
- [`create()`](https://reference.langchain.com/python/langgraph-sdk/_sync/runs/SyncRunsClient/create)
- [`create_batch()`](https://reference.langchain.com/python/langgraph-sdk/_sync/runs/SyncRunsClient/create_batch)
- [`wait()`](https://reference.langchain.com/python/langgraph-sdk/_sync/runs/SyncRunsClient/wait)
- [`list()`](https://reference.langchain.com/python/langgraph-sdk/_sync/runs/SyncRunsClient/list)
- [`get()`](https://reference.langchain.com/python/langgraph-sdk/_sync/runs/SyncRunsClient/get)
- [`cancel()`](https://reference.langchain.com/python/langgraph-sdk/_sync/runs/SyncRunsClient/cancel)
- [`cancel_many()`](https://reference.langchain.com/python/langgraph-sdk/_sync/runs/SyncRunsClient/cancel_many)
- [`join()`](https://reference.langchain.com/python/langgraph-sdk/_sync/runs/SyncRunsClient/join)
- [`join_stream()`](https://reference.langchain.com/python/langgraph-sdk/_sync/runs/SyncRunsClient/join_stream)
- [`delete()`](https://reference.langchain.com/python/langgraph-sdk/_sync/runs/SyncRunsClient/delete)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/_sync/runs.py#L56)