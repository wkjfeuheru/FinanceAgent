# RunsClient

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/_async/runs/RunsClient)

Client for managing runs in LangGraph.

A run is a single assistant invocation with optional input, config, context, and metadata.
This client manages runs, which can be stateful (on threads) or stateless.

???+ example "Example"

    ```python
    client = get_client(url="http://localhost:2024")
    run = await client.runs.create(assistant_id="asst_123", thread_id="thread_456", input={"query": "Hello"})
    ```

## Signature

```python
RunsClient(
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

- [`stream()`](https://reference.langchain.com/python/langgraph-sdk/_async/runs/RunsClient/stream)
- [`create()`](https://reference.langchain.com/python/langgraph-sdk/_async/runs/RunsClient/create)
- [`create_batch()`](https://reference.langchain.com/python/langgraph-sdk/_async/runs/RunsClient/create_batch)
- [`wait()`](https://reference.langchain.com/python/langgraph-sdk/_async/runs/RunsClient/wait)
- [`list()`](https://reference.langchain.com/python/langgraph-sdk/_async/runs/RunsClient/list)
- [`get()`](https://reference.langchain.com/python/langgraph-sdk/_async/runs/RunsClient/get)
- [`cancel()`](https://reference.langchain.com/python/langgraph-sdk/_async/runs/RunsClient/cancel)
- [`cancel_many()`](https://reference.langchain.com/python/langgraph-sdk/_async/runs/RunsClient/cancel_many)
- [`join()`](https://reference.langchain.com/python/langgraph-sdk/_async/runs/RunsClient/join)
- [`join_stream()`](https://reference.langchain.com/python/langgraph-sdk/_async/runs/RunsClient/join_stream)
- [`delete()`](https://reference.langchain.com/python/langgraph-sdk/_async/runs/RunsClient/delete)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/_async/runs.py#L56)