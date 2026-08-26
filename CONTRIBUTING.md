# Contributing

Use Python 3.10 or newer and create an isolated environment:

```bash
python -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[dev]"
```

Run the full local gate before submitting a change:

```bash
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python -m mypy src tests
.venv/bin/python -m pytest -q
rm -rf dist
.venv/bin/python -m build
.venv/bin/python -m twine check dist/*
wheelhouse_dir="$(mktemp -d "${TMPDIR:-/tmp}/agentcommunity-wheelhouse.XXXXXX")"
trap 'rm -rf -- "$wheelhouse_dir"' EXIT
bash scripts/prepare-wheelhouse.sh "$wheelhouse_dir"
bash scripts/verify-artifacts.sh dist "$wheelhouse_dir"
```

Wheelhouse preparation is the only artifact-check step allowed to contact a
package index. The verifier installs exclusively from that explicit directory
with pip's `--no-index` mode and fails if the wheelhouse is incomplete.

The default test suite is entirely offline and excludes tests marked
`production`. Do not run the production smoke test as part of ordinary local or
pull-request verification. Keep changes focused, add a failing test before a
behavior change, and update documentation with the code it describes.
