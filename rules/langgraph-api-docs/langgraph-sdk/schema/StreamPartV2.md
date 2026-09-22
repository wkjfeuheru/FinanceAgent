# StreamPartV2

> **Type Alias** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/schema/StreamPartV2)

Discriminated union of all v2 stream part types.

Use `part["type"]` to narrow the type.

## Signature

```python
StreamPartV2 = ValuesStreamPart | UpdatesStreamPart | MessagesPartialStreamPart | MessagesCompleteStreamPart | MessagesMetadataStreamPart | MessagesTupleStreamPart | CustomStreamPart | CheckpointsStreamPart | TasksStreamPart | DebugStreamPart | MetadataStreamPart
```

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/schema.py#L856)