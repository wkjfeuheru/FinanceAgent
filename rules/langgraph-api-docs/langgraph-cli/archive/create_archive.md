# create_archive

> **Function** in `langgraph_cli`

📖 [View in docs](https://reference.langchain.com/python/langgraph-cli/archive/create_archive)

Context manager that creates a .tar.gz archive of the project source.

Uses _assemble_local_deps to discover local dependencies referenced in
langgraph.json, including those outside config.parent (monorepo case).

The archive preserves the real filesystem layout relative to the common
ancestor of config.parent and all external dependency directories, so that
relative references (e.g. `../shared-lib`) resolve correctly after
extraction.

Yields (archive_path, file_size, config_relative_path).  The temporary
directory holding the archive is cleaned up automatically on exit.

## Signature

```python
create_archive(
    config_path: pathlib.Path,
    config: Config,
)
```

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/1a9baae9592e0c21336f6e09c891ba75481fd657/libs/cli/langgraph_cli/archive.py#L62)