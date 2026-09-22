# SyncStoreClient

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/_sync/store/SyncStoreClient)

A client for synchronous operations on a key-value store.

Provides methods to interact with a remote key-value store, allowing
storage and retrieval of items within namespaced hierarchies.

???+ example "Example"

    ```python
    client = get_sync_client(url="http://localhost:2024"))
    client.store.put_item(["users", "profiles"], "user123", {"name": "Alice", "age": 30})
    ```

## Signature

```python
SyncStoreClient(
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

- [`put_item()`](https://reference.langchain.com/python/langgraph-sdk/_sync/store/SyncStoreClient/put_item)
- [`get_item()`](https://reference.langchain.com/python/langgraph-sdk/_sync/store/SyncStoreClient/get_item)
- [`delete_item()`](https://reference.langchain.com/python/langgraph-sdk/_sync/store/SyncStoreClient/delete_item)
- [`search_items()`](https://reference.langchain.com/python/langgraph-sdk/_sync/store/SyncStoreClient/search_items)
- [`list_namespaces()`](https://reference.langchain.com/python/langgraph-sdk/_sync/store/SyncStoreClient/list_namespaces)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/_sync/store.py#L18)