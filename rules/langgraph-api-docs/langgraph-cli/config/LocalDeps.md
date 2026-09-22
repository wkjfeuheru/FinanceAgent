# LocalDeps

> **Class** in `langgraph_cli`

📖 [View in docs](https://reference.langchain.com/python/langgraph-cli/config/LocalDeps)

A container for referencing and managing local Python dependencies.

A "local dependency" is any entry in the config's `dependencies` list
that starts with "." (dot), denoting a relative path
to a local directory containing Python code.

For each local dependency, the system inspects its directory to
determine how it should be installed inside the Docker container.

Specifically, we detect:

- **Real packages**: Directories containing a `pyproject.toml` or a `setup.py`.
  These can be installed with pip as a regular Python package.
- **Faux packages**: Directories that do not include a `pyproject.toml` or
  `setup.py` but do contain Python files and possibly an `__init__.py`. For
  these, the code dynamically generates a minimal `pyproject.toml` in the
  Docker image so that they can still be installed with pip.
- **Requirements files**: If a local dependency directory
  has a `requirements.txt`, it is tracked so that those dependencies
  can be installed within the Docker container before installing the local package.

## Signature

```python
LocalDeps()
```

## Extends

- `NamedTuple`

## Properties

- `pip_reqs`
- `real_pkgs`
- `faux_pkgs`
- `working_dir`
- `additional_contexts`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/1a9baae9592e0c21336f6e09c891ba75481fd657/libs/cli/langgraph_cli/config.py#L651)