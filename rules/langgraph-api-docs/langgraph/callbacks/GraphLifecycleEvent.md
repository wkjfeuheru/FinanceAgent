# GraphLifecycleEvent

> **Type Alias** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/callbacks/GraphLifecycleEvent)

Union of all public graph lifecycle callback event payloads.

Use this alias when a callback or helper can receive either interrupt or resume
lifecycle events.

## Signature

```python
GraphLifecycleEvent: TypeAlias = GraphInterruptEvent | GraphResumeEvent
```

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/callbacks.py#L79)