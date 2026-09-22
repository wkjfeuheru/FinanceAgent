# APIConnectionError

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/errors/APIConnectionError)

## Signature

```python
APIConnectionError(
    self,
    *,
    message: str = 'Connection error.',
    request: httpx.Request,
)
```

## Extends

- `APIError`

## Constructors

```python
__init__(
    self,
    *,
    message: str = 'Connection error.',
    request: httpx.Request,
) -> None
```

| Name | Type |
|------|------|
| `message` | `str` |
| `request` | `httpx.Request` |


---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/errors.py#L96)