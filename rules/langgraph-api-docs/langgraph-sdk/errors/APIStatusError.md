# APIStatusError

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/errors/APIStatusError)

## Signature

```python
APIStatusError(
    self,
    message: str,
    *,
    response: httpx.Response,
    body: object | None,
)
```

## Extends

- `APIError`

## Constructors

```python
__init__(
    self,
    message: str,
    *,
    response: httpx.Response,
    body: object | None,
) -> None
```

| Name | Type |
|------|------|
| `message` | `str` |
| `response` | `httpx.Response` |
| `body` | `object \| None` |


## Properties

- `response`
- `status_code`
- `request_id`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/errors.py#L82)