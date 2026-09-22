# GraphRecursionError

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/errors/GraphRecursionError)

Raised when the graph has exhausted the maximum number of steps.

This prevents infinite loops. To increase the maximum number of steps,
run your graph with a config specifying a higher `recursion_limit`.

Troubleshooting guides:

- [`GRAPH_RECURSION_LIMIT`](https://docs.langchain.com/oss/python/langgraph/GRAPH_RECURSION_LIMIT)

Examples:

    graph = builder.compile()
    graph.invoke(
        {"messages": [("user", "Hello, world!")]},
        # The config is the second positional argument
        {"recursion_limit": 1000},
    )

## Signature

```python
GraphRecursionError()
```

## Extends

- `RecursionError`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/errors.py#L67)