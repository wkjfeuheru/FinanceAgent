# validate_interleave_channels

> **Function** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/stream/decoders/validate_interleave_channels)

Reject reserved protocol channel names before they hit the fallback.

Genuine extension names pass through untouched; only names that
``infer_channel`` treats as built-in methods without an interleave decoder
are rejected, so a typo'd or unsupported protocol channel surfaces an error
instead of an empty stream.

## Signature

```python
validate_interleave_channels(
    channels: list[str],
) -> None
```

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/stream/decoders.py#L34)