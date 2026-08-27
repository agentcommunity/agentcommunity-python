#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 WHEELHOUSE_DIRECTORY" >&2
  exit 64
fi

mkdir -p -- "$1"
wheelhouse_dir="$(cd "$1" && pwd -P)"
if [[ "$wheelhouse_dir" != /* || "$wheelhouse_dir" == "/" ]]; then
  echo "could not resolve a safe wheelhouse directory" >&2
  exit 66
fi
if [[ -n "$(find "$wheelhouse_dir" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
  echo "wheelhouse directory must be empty: $wheelhouse_dir" >&2
  exit 65
fi

python_bin=""
for candidate in "${PYTHON:-}" python "$PWD/.venv/bin/python" python3; do
  if [[ -n "$candidate" ]] && command -v "$candidate" >/dev/null 2>&1; then
    python_bin="$candidate"
    break
  fi
done
if [[ -z "$python_bin" ]]; then
  echo "no Python interpreter was found" >&2
  exit 69
fi

PIP_DISABLE_PIP_VERSION_CHECK=1 "$python_bin" -m pip download \
  --only-binary=:all: \
  --dest "$wheelhouse_dir" \
  'hatchling==1.30.1' \
  'jsonschema>=4.20,<5' \
  'mcp>=2.1.1,<3' \
  'pydantic>=2.12,<3'

echo "prepared wheelhouse: $wheelhouse_dir"
