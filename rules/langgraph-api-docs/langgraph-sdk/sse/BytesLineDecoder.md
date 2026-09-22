# BytesLineDecoder

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/sse/BytesLineDecoder)

Handles incrementally reading lines from text.

Has the same behaviour as the stdllib bytes splitlines,
but handling the input iteratively.

## Signature

```python
BytesLineDecoder(
    self,
)
```

## Constructors

```python
__init__(
    self,
) -> None
```


## Properties

- `buffer`
- `trailing_cr`

## Methods

- [`decode()`](https://reference.langchain.com/python/langgraph-sdk/sse/BytesLineDecoder/decode)
- [`flush()`](https://reference.langchain.com/python/langgraph-sdk/sse/BytesLineDecoder/flush)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/sse.py#L17)