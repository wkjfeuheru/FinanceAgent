# StateNode

> **Type Alias** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/graph/_node/StateNode)

## Signature

```python
StateNode: TypeAlias = _Node[NodeInputT] | _NodeWithConfig[NodeInputT] | _NodeWithWriter[NodeInputT] | _NodeWithStore[NodeInputT] | _NodeWithWriterStore[NodeInputT] | _NodeWithConfigWriter[NodeInputT] | _NodeWithConfigStore[NodeInputT] | _NodeWithConfigWriterStore[NodeInputT] | _NodeWithRuntime[NodeInputT, ContextT] | Runnable[NodeInputT, Any]
```

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/graph/_node.py#L70)