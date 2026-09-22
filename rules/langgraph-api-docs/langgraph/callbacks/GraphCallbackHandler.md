# GraphCallbackHandler

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/callbacks/GraphCallbackHandler)

Base class for graph-level lifecycle callbacks.

Subclass this handler to observe graph lifecycle transitions that are
specific to LangGraph execution, rather than generic LangChain runnable
callbacks.

Instances can be passed through `config["callbacks"]` when invoking a
graph. Only handlers that inherit from `GraphCallbackHandler` receive these
lifecycle events.

## Signature

```python
GraphCallbackHandler()
```

## Extends

- `BaseCallbackHandler`

## Methods

- [`on_interrupt()`](https://reference.langchain.com/python/langgraph/callbacks/GraphCallbackHandler/on_interrupt)
- [`on_resume()`](https://reference.langchain.com/python/langgraph/callbacks/GraphCallbackHandler/on_resume)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/callbacks.py#L87)