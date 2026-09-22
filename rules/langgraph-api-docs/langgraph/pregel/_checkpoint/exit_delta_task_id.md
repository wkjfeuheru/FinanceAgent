# exit_delta_task_id

> **Function** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/pregel/_checkpoint/exit_delta_task_id)

Synthetic task id for exit-mode DeltaChannel writes.

Embeds the superstep in the first UUID group so `ORDER BY task_id, idx`
preserves chronological order while remaining a valid RFC UUID (required by
Postgres `checkpoint_writes.task_id uuid` columns).

## Signature

```python
exit_delta_task_id(
    step: int,
    task_id: str,
) -> str
```

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/pregel/_checkpoint.py#L38)