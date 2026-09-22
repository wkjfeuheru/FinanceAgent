# StoreClient

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/_async/store/StoreClient)

Client for interacting with the graph's shared storage.

The Store provides a key-value storage system for persisting data across graph executions,
allowing for stateful operations and data sharing across threads.

???+ example "Example"

    ```python
    client = get_client(url="http://localhost:2024")
    await client.store.put_item(["users", "user123"], "mem-123451342", {"name": "Alice", "score": 100})
    ```

## Signature

```python
StoreClient(
    self,
    http: HttpClient,
)
```

## Constructors

```python
__init__(
    self,
    http: HttpClient,
) -> None
```

| Name | Type |
|------|------|
| `http` | `HttpClient` |


## Properties

- `http`

## Methods

- [`put_item()`](https://reference.langchain.com/python/langgraph-sdk/_async/store/StoreClient/put_item)
- [`get_item()`](https://reference.langchain.com/python/langgraph-sdk/_async/store/StoreClient/get_item)
- [`delete_item()`](https://reference.langchain.com/python/langgraph-sdk/_async/store/StoreClient/delete_item)
- [`search_items()`](https://reference.langchain.com/python/langgraph-sdk/_async/store/StoreClient/search_items)
- [`list_namespaces()`](https://reference.langchain.com/python/langgraph-sdk/_async/store/StoreClient/list_namespaces)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/_async/store.py#L18)