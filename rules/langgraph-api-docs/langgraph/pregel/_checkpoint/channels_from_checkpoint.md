# channels_from_checkpoint

> **Function** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/pregel/_checkpoint/channels_from_checkpoint)

Hydrate channels from a checkpoint.

For most channels, `spec.from_checkpoint(checkpoint["channel_values"][k])`
is sufficient. `DeltaChannel` is the exception: when the channel is
absent from `channel_values`, an ancestor walk via
`saver.get_delta_channel_history` is required to find the nearest seed
(`_DeltaSnapshot` blob or pre-migration plain value) and accumulate
the writes between it and the target. All delta channels needing
replay are batched into a single saver call.

## Signature

```python
channels_from_checkpoint(
    specs: Mapping[str, BaseChannel | ManagedValueSpec],
    checkpoint: Checkpoint,
    *,
    saver: BaseCheckpointSaver | None = None,
    config: RunnableConfig | None = None,
) -> tuple[Mapping[str, BaseChannel], ManagedValueMapping]
```

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/pregel/_checkpoint.py#L153)