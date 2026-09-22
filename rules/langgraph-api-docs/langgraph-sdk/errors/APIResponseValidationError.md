# APIResponseValidationError

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/errors/APIResponseValidationError)

## Signature

```python
APIResponseValidationError(
    self,
    response: httpx.Response,
    body: object | None,
    *,
    message: str | None = None,
)
```

## Extends

- `APIError`

## Constructors

```python
__init__(
    self,
    response: httpx.Response,
    body: object | None,
    *,
    message: str | None = None,
) -> None
```

| Name | Type |
|------|------|
| `response` | `httpx.Response` |
| `body` | `object \| None` |
| `message` | `str \| None` |


## Properties

- `response`
- `status_code`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/errors.py#L62)