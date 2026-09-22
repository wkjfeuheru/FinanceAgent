# SyncCronClient

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/_sync/cron/SyncCronClient)

Synchronous client for managing cron jobs in LangGraph.

This class provides methods to create and manage scheduled tasks (cron jobs) for automated graph executions.

???+ example "Example"

    ```python
    client = get_sync_client(url="http://localhost:8123")
    cron_job = client.crons.create_for_thread(thread_id="thread_123", assistant_id="asst_456", schedule="0 * * * *")
    ```

!!! note "Feature Availability"

    The crons client functionality is not supported on all licenses.
    Please check the relevant license documentation for the most up-to-date
    details on feature availability.

## Signature

```python
SyncCronClient(
    self,
    http_client: SyncHttpClient,
)
```

## Constructors

```python
__init__(
    self,
    http_client: SyncHttpClient,
) -> None
```

| Name | Type |
|------|------|
| `http_client` | `SyncHttpClient` |


## Properties

- `http`

## Methods

- [`create_for_thread()`](https://reference.langchain.com/python/langgraph-sdk/_sync/cron/SyncCronClient/create_for_thread)
- [`create()`](https://reference.langchain.com/python/langgraph-sdk/_sync/cron/SyncCronClient/create)
- [`delete()`](https://reference.langchain.com/python/langgraph-sdk/_sync/cron/SyncCronClient/delete)
- [`update()`](https://reference.langchain.com/python/langgraph-sdk/_sync/cron/SyncCronClient/update)
- [`search()`](https://reference.langchain.com/python/langgraph-sdk/_sync/cron/SyncCronClient/search)
- [`count()`](https://reference.langchain.com/python/langgraph-sdk/_sync/cron/SyncCronClient/count)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/_sync/cron.py#L30)