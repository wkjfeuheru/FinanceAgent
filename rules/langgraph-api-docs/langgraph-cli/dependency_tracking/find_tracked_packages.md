# find_tracked_packages

> **Function** in `langgraph_cli`

📖 [View in docs](https://reference.langchain.com/python/langgraph-cli/dependency_tracking/find_tracked_packages)

Return every tracked package found in deps as `<name>:<version>` entries.

`config` is the absolute path to `langgraph.json`; dep paths in
`config_json["dependencies"]` are resolved relative to its parent.
Detection precedence per package: uv.lock resolved > pyproject.toml /
requirements.txt specifier > bare reference > extras bracket (last
two recorded as "unknown"). Output is ordered by `TRACKED_PACKAGES`.

## Signature

```python
find_tracked_packages(
    config: pathlib.Path,
    config_json: dict,
) -> list[str]
```

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/1a9baae9592e0c21336f6e09c891ba75481fd657/libs/cli/langgraph_cli/dependency_tracking.py#L98)