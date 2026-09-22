# apply_writes

> **Function** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/pregel/_algo/apply_writes)

Apply writes from a set of tasks (usually the tasks from a Pregel step)
to the checkpoint and channels, and return managed values writes to be applied
externally.

## Signature

```python
apply_writes(
    checkpoint: Checkpoint,
    channels: Mapping[str, BaseChannel],
    tasks: Iterable[WritesProtocol],
    get_next_version: GetNextVersion | None,
    trigger_to_nodes: Mapping[str, Sequence[str]],
) -> set[str]
```

## Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `checkpoint` | `Checkpoint` | Yes | The checkpoint to update. |
| `channels` | `Mapping[str, BaseChannel]` | Yes | The channels to update. |
| `tasks` | `Iterable[WritesProtocol]` | Yes | The tasks to apply writes from. |
| `get_next_version` | `GetNextVersion \| None` | Yes | Optional function to determine the next version of a channel. |
| `trigger_to_nodes` | `Mapping[str, Sequence[str]]` | Yes | Mapping of channel names to the set of nodes that can be triggered by updates to that channel. |

## Returns

`set[str]`

Set of channels that were updated in this step.

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/pregel/_algo.py#L232)