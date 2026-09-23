# Contributing

Install with `python -m pip install -e '.[dev,numpy]'` and run:

```bash
python -m unittest discover -s tests -v
python -m mypy src/rag_preflight
python -m build
```

Use synthetic or public test data only. For a bug, provide a minimal input, package
and Python version, expected/actual report, and any source/state schema involved.
Add a regression test for changes to deletion guards, source coverage, identity,
provenance or state updates. Keep core imports independent of third-party services.
Changes to hashes, schemas and state semantics require explicit compatibility review.

Build output belongs in ignored dist/ locally and release attachments when published,
not in tracked source. The delivered ZIP separates source from downloadable artifacts.

Before publishing: verify the PyPI name, add real repository/docs/issue URLs when
available, review author metadata, run the supported-platform CI, and validate the
actual parser/provider/vector-store integration. No release is published automatically.
