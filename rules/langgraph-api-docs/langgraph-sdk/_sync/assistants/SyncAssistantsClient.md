# SyncAssistantsClient

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/_sync/assistants/SyncAssistantsClient)

Client for managing assistants in LangGraph synchronously.

This class provides methods to interact with assistants, which are versioned configurations of your graph.

???+ example "Example"

    ```python
    client = get_sync_client(url="http://localhost:2024")
    assistant = client.assistants.get("assistant_id_123")
    ```

## Signature

```python
SyncAssistantsClient(
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

- [`get()`](https://reference.langchain.com/python/langgraph-sdk/_sync/assistants/SyncAssistantsClient/get)
- [`get_graph()`](https://reference.langchain.com/python/langgraph-sdk/_sync/assistants/SyncAssistantsClient/get_graph)
- [`get_schemas()`](https://reference.langchain.com/python/langgraph-sdk/_sync/assistants/SyncAssistantsClient/get_schemas)
- [`get_subgraphs()`](https://reference.langchain.com/python/langgraph-sdk/_sync/assistants/SyncAssistantsClient/get_subgraphs)
- [`create()`](https://reference.langchain.com/python/langgraph-sdk/_sync/assistants/SyncAssistantsClient/create)
- [`update()`](https://reference.langchain.com/python/langgraph-sdk/_sync/assistants/SyncAssistantsClient/update)
- [`delete()`](https://reference.langchain.com/python/langgraph-sdk/_sync/assistants/SyncAssistantsClient/delete)
- [`search()`](https://reference.langchain.com/python/langgraph-sdk/_sync/assistants/SyncAssistantsClient/search)
- [`count()`](https://reference.langchain.com/python/langgraph-sdk/_sync/assistants/SyncAssistantsClient/count)
- [`get_versions()`](https://reference.langchain.com/python/langgraph-sdk/_sync/assistants/SyncAssistantsClient/get_versions)
- [`set_latest()`](https://reference.langchain.com/python/langgraph-sdk/_sync/assistants/SyncAssistantsClient/set_latest)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/_sync/assistants.py#L29)