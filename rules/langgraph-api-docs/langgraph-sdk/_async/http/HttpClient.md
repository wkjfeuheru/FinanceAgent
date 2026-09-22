# HttpClient

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/_async/http/HttpClient)

Handle async requests to the LangGraph API.

Adds additional error messaging & content handling above the
provided httpx client.

## Signature

```python
HttpClient(
    self,
    client: httpx.AsyncClient,
)
```

## Constructors

```python
__init__(
    self,
    client: httpx.AsyncClient,
) -> None
```

| Name | Type |
|------|------|
| `client` | `httpx.AsyncClient` |


## Properties

- `client`

## Methods

- [`get()`](https://reference.langchain.com/python/langgraph-sdk/_async/http/HttpClient/get)
- [`post()`](https://reference.langchain.com/python/langgraph-sdk/_async/http/HttpClient/post)
- [`put()`](https://reference.langchain.com/python/langgraph-sdk/_async/http/HttpClient/put)
- [`patch()`](https://reference.langchain.com/python/langgraph-sdk/_async/http/HttpClient/patch)
- [`delete()`](https://reference.langchain.com/python/langgraph-sdk/_async/http/HttpClient/delete)
- [`request_reconnect()`](https://reference.langchain.com/python/langgraph-sdk/_async/http/HttpClient/request_reconnect)
- [`stream()`](https://reference.langchain.com/python/langgraph-sdk/_async/http/HttpClient/stream)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/_async/http.py#L26)