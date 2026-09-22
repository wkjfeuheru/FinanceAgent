# ThreadsClient

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/_async/threads/ThreadsClient)

Client for managing threads in LangGraph.

A thread maintains the state of a graph across multiple interactions/invocations (aka runs).
It accumulates and persists the graph's state, allowing for continuity between separate
invocations of the graph.

???+ example "Example"

    ```python
    client = get_client(url="http://localhost:2024"))
    new_thread = await client.threads.create(metadata={"user_id": "123"})
    ```

## Signature

```python
ThreadsClient(
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

- [`get()`](https://reference.langchain.com/python/langgraph-sdk/_async/threads/ThreadsClient/get)
- [`create()`](https://reference.langchain.com/python/langgraph-sdk/_async/threads/ThreadsClient/create)
- [`update()`](https://reference.langchain.com/python/langgraph-sdk/_async/threads/ThreadsClient/update)
- [`delete()`](https://reference.langchain.com/python/langgraph-sdk/_async/threads/ThreadsClient/delete)
- [`search()`](https://reference.langchain.com/python/langgraph-sdk/_async/threads/ThreadsClient/search)
- [`count()`](https://reference.langchain.com/python/langgraph-sdk/_async/threads/ThreadsClient/count)
- [`copy()`](https://reference.langchain.com/python/langgraph-sdk/_async/threads/ThreadsClient/copy)
- [`prune()`](https://reference.langchain.com/python/langgraph-sdk/_async/threads/ThreadsClient/prune)
- [`get_state()`](https://reference.langchain.com/python/langgraph-sdk/_async/threads/ThreadsClient/get_state)
- [`update_state()`](https://reference.langchain.com/python/langgraph-sdk/_async/threads/ThreadsClient/update_state)
- [`get_history()`](https://reference.langchain.com/python/langgraph-sdk/_async/threads/ThreadsClient/get_history)
- [`stream()`](https://reference.langchain.com/python/langgraph-sdk/_async/threads/ThreadsClient/stream)
- [`join_stream()`](https://reference.langchain.com/python/langgraph-sdk/_async/threads/ThreadsClient/join_stream)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/_async/threads.py#L30)