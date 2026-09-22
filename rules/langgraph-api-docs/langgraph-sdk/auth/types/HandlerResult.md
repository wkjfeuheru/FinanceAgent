# HandlerResult

> **Type Alias** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/auth/types/HandlerResult)

The result of a handler can be:
* None | True: accept the request.
* False: reject the request with a 403 error
* FilterType: filter to apply

## Signature

```python
HandlerResult = None | bool | FilterType
```

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/auth/types.py#L138)