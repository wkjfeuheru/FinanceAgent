# SyncHttpClient

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/_sync/http/SyncHttpClient)

Handle synchronous requests to the LangGraph API.

Provides error messaging and content handling enhancements above the
underlying httpx client, mirroring the interface of [HttpClient](#HttpClient)
but for sync usage.

## Signature

```python
SyncHttpClient(
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

- `client`

## Methods

- [`get()`](https://reference.langchain.com/python/langgraph-sdk/_sync/http/SyncHttpClient/get)
- [`post()`](https://reference.langchain.com/python/langgraph-sdk/_sync/http/SyncHttpClient/post)
- [`put()`](https://reference.langchain.com/python/langgraph-sdk/_sync/http/SyncHttpClient/put)
- [`patch()`](https://reference.langchain.com/python/langgraph-sdk/_sync/http/SyncHttpClient/patch)
- [`delete()`](https://reference.langchain.com/python/langgraph-sdk/_sync/http/SyncHttpClient/delete)
- [`request_reconnect()`](https://reference.langchain.com/python/langgraph-sdk/_sync/http/SyncHttpClient/request_reconnect)
- [`stream()`](https://reference.langchain.com/python/langgraph-sdk/_sync/http/SyncHttpClient/stream)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/_sync/http.py#L25)