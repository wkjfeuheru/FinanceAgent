# ExtensionsDecoder

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/stream/decoders/ExtensionsDecoder)

Yields `params.data` from one named custom channel.

Mirrors `_ExtensionProjection._iter` (`_async/stream.py:1278-1299`), with
an added name filter so it can share one subscription in interleave.

## Signature

```python
ExtensionsDecoder(
    self,
    name: str,
)
```

## Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `name` | `str` | Yes | The extension name. Only `custom` events whose `data["name"]` matches are consumed. |

## Constructors

```python
__init__(
    self,
    name: str,
)
```

| Name | Type |
|------|------|
| `name` | `str` |


## Methods

- [`feed()`](https://reference.langchain.com/python/langgraph-sdk/stream/decoders/ExtensionsDecoder/feed)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/stream/decoders.py#L334)