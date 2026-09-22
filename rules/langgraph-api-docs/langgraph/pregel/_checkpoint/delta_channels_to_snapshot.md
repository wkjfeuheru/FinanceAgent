# delta_channels_to_snapshot

> **Function** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/pregel/_checkpoint/delta_channels_to_snapshot)

Return the set of DeltaChannel names that should snapshot now.

A channel snapshots when EITHER its accumulated update count reaches
`snapshot_frequency` OR the total supersteps since its last snapshot
reaches `DELTA_MAX_SUPERSTEPS_SINCE_SNAPSHOT`. This is a pure
predicate — no mutation.

## Signature

```python
delta_channels_to_snapshot(
    channels: Mapping[str, BaseChannel],
    counters_since_delta_snapshot: Mapping[str, tuple[int, int]],
) -> set[str]
```

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/pregel/_checkpoint.py#L49)