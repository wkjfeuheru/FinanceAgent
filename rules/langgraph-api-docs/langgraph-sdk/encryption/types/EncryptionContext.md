# EncryptionContext

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/encryption/types/EncryptionContext)

Context passed to encryption/decryption handlers.

Contains arbitrary non-secret key-values that will be stored on encrypt.
These key-values are intended to be sent to an external service that
manages keys and handles the actual encryption and decryption of data.

## Signature

```python
EncryptionContext(
    self,
    model: str | None = None,
    metadata: dict[str, typing.Any] | None = None,
    field: str | None = None,
)
```

## Constructors

```python
__init__(
    self,
    model: str | None = None,
    metadata: dict[str, typing.Any] | None = None,
    field: str | None = None,
)
```

| Name | Type |
|------|------|
| `model` | `str \| None` |
| `metadata` | `dict[str, typing.Any] \| None` |
| `field` | `str \| None` |


## Properties

- `model`
- `field`
- `metadata`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/encryption/types.py#L17)