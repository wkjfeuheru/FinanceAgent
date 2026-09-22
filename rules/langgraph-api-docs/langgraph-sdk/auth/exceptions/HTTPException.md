# HTTPException

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/auth/exceptions/HTTPException)

HTTP exception that you can raise to return a specific HTTP error response.

Since this is defined in the auth module, we default to a 401 status code.

## Signature

```python
HTTPException(
    self,
    status_code: int = 401,
    detail: str | None = None,
    headers: Mapping[str, str] | None = None,
)
```

## Description

**Example:**

Default:
```python
raise HTTPException()
# HTTPException(status_code=401, detail='Unauthorized')
```

Add headers:
```python
raise HTTPException(headers={"X-Custom-Header": "Custom Value"})
# HTTPException(status_code=401, detail='Unauthorized', headers={"WWW-Authenticate": "Bearer"})
```

Custom error:
```python
raise HTTPException(status_code=404, detail="Not found")
```

## Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `status_code` | `int` | No | HTTP status code for the error. Defaults to 401 "Unauthorized". (default: `401`) |
| `detail` | `str \| None` | No | Detailed error message. If `None`, uses a default message based on the status code. (default: `None`) |
| `headers` | `Mapping[str, str] \| None` | No | Additional HTTP headers to include in the error response. (default: `None`) |

## Extends

- `Exception`

## Constructors

```python
__init__(
    self,
    status_code: int = 401,
    detail: str | None = None,
    headers: Mapping[str, str] | None = None,
) -> None
```

| Name | Type |
|------|------|
| `status_code` | `int` |
| `detail` | `str \| None` |
| `headers` | `Mapping[str, str] \| None` |


## Properties

- `status_code`
- `detail`
- `headers`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/auth/exceptions.py#L9)