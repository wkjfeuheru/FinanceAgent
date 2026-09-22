# AssistantsClient

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/_async/assistants/AssistantsClient)

Client for managing assistants in LangGraph.

This class provides methods to interact with assistants,
which are versioned configurations of your graph.

???+ example "Example"

    ```python
    client = get_client(url="http://localhost:2024")
    assistant = await client.assistants.get("assistant_id_123")
    ```

## Signature

```python
AssistantsClient(
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

- [`get()`](https://reference.langchain.com/python/langgraph-sdk/_async/assistants/AssistantsClient/get)
- [`get_graph()`](https://reference.langchain.com/python/langgraph-sdk/_async/assistants/AssistantsClient/get_graph)
- [`get_schemas()`](https://reference.langchain.com/python/langgraph-sdk/_async/assistants/AssistantsClient/get_schemas)
- [`get_subgraphs()`](https://reference.langchain.com/python/langgraph-sdk/_async/assistants/AssistantsClient/get_subgraphs)
- [`create()`](https://reference.langchain.com/python/langgraph-sdk/_async/assistants/AssistantsClient/create)
- [`update()`](https://reference.langchain.com/python/langgraph-sdk/_async/assistants/AssistantsClient/update)
- [`delete()`](https://reference.langchain.com/python/langgraph-sdk/_async/assistants/AssistantsClient/delete)
- [`search()`](https://reference.langchain.com/python/langgraph-sdk/_async/assistants/AssistantsClient/search)
- [`count()`](https://reference.langchain.com/python/langgraph-sdk/_async/assistants/AssistantsClient/count)
- [`get_versions()`](https://reference.langchain.com/python/langgraph-sdk/_async/assistants/AssistantsClient/get_versions)
- [`set_latest()`](https://reference.langchain.com/python/langgraph-sdk/_async/assistants/AssistantsClient/set_latest)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/_async/assistants.py#L29)