# APIError

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/errors/APIError)

## Signature

```python
APIError(
    self,
    message: str,
    response_or_request: httpx.Response | httpx.Request,
    *,
    body: object | None,
)
```

## Extends

- `httpx.HTTPStatusError`
- `LangGraphError`

## Constructors

```python
__init__(
    self,
    message: str,
    response_or_request: httpx.Response | httpx.Request,
    *,
    body: object | None,
) -> None
```

| Name | Type |
|------|------|
| `message` | `str` |
| `response_or_request` | `httpx.Response \| httpx.Request` |
| `body` | `object \| None` |


## Properties

- `message`
- `request`
- `body`
- `code`
- `param`
- `type`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/errors.py#L17)