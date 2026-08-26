#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 ARTIFACT_DIRECTORY" >&2
  exit 64
fi

if [[ ! -d "$1" ]]; then
  echo "artifact directory does not exist: $1" >&2
  exit 66
fi

artifact_dir="$(cd "$1" && pwd -P)"
if [[ "$artifact_dir" != /* || "$artifact_dir" == "/" ]]; then
  echo "could not resolve a safe artifact directory" >&2
  exit 66
fi

shopt -s nullglob
wheels=("$artifact_dir"/*.whl)
sdists=("$artifact_dir"/*.tar.gz)
shopt -u nullglob

if [[ ${#wheels[@]} -ne 1 || ${#sdists[@]} -ne 1 ]]; then
  echo "expected exactly one wheel and one .tar.gz sdist in $artifact_dir" >&2
  exit 65
fi

wheel="${wheels[0]}"
sdist="${sdists[0]}"
temp_dir="$(mktemp -d "${TMPDIR:-/tmp}/agentcommunity-artifacts.XXXXXX")"
case "$temp_dir" in
  /*/agentcommunity-artifacts.*) ;;
  *)
    echo "refusing unsafe temporary path: $temp_dir" >&2
    exit 70
    ;;
esac

cleanup() {
  if [[ -n "${temp_dir:-}" && -d "$temp_dir" ]]; then
    rm -rf -- "$temp_dir"
  fi
}
trap cleanup EXIT HUP INT TERM

unset PYTHONPATH
python_bin=""
for candidate in "${PYTHON:-}" python "$PWD/.venv/bin/python" python3; do
  if [[ -n "$candidate" ]] && command -v "$candidate" >/dev/null 2>&1 \
    && "$candidate" -c "import twine" >/dev/null 2>&1; then
    python_bin="$candidate"
    break
  fi
done
if [[ -z "$python_bin" ]]; then
  echo "no Python interpreter with Twine installed was found" >&2
  exit 69
fi
"$python_bin" -m twine check "$wheel" "$sdist"

"$python_bin" - "$wheel" "$sdist" <<'PY'
from __future__ import annotations

import re
import sys
import tarfile
import zipfile
from pathlib import PurePosixPath

wheel_path, sdist_path = sys.argv[1:]
expected_package_files = {
    "agentcommunity/__init__.py",
    "agentcommunity/_transport.py",
    "agentcommunity/client.py",
    "agentcommunity/errors.py",
    "agentcommunity/models.py",
    "agentcommunity/py.typed",
}
def validate_name(archive_path: str, name: str) -> None:
    parts = PurePosixPath(name).parts
    lowered = {part.lower() for part in parts}
    assert ".git" not in parts, f"git metadata shipped in {archive_path}: {name}"
    assert not lowered.intersection(
        {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
    ), f"cache shipped in {archive_path}: {name}"
    assert not any(
        part == ".env" or part.startswith(".env.") for part in parts
    ), f"environment file shipped in {archive_path}: {name}"
    assert "uv.lock" not in parts, f"local lock file shipped in {archive_path}: {name}"
    assert "tests" not in parts, f"tests-only content shipped in {archive_path}: {name}"
    assert not any(
        part.lower() in {"credentials", "secrets"}
        or part.lower().endswith((".key", ".pem"))
        for part in parts
    ), f"possible secret material shipped in {archive_path}: {name}"


def validate_contents(archive_path: str, name: str, data: bytes) -> None:
    assert re.search(rb"gitdir:\s*(?:/|[A-Za-z]:[\\/])", data) is None, (
        f"absolute gitdir reference shipped in {archive_path}: {name}"
    )


with zipfile.ZipFile(wheel_path) as archive:
    for name in archive.namelist():
        validate_name(wheel_path, name)
        if not name.endswith("/"):
            validate_contents(wheel_path, name, archive.read(name))

with tarfile.open(sdist_path, mode="r:gz") as archive:
    for member in archive.getmembers():
        name = member.name
        validate_name(sdist_path, name)
        if member.isfile():
            extracted = archive.extractfile(member)
            assert extracted is not None
            validate_contents(sdist_path, name, extracted.read())

with zipfile.ZipFile(wheel_path) as archive:
    wheel_names = set(archive.namelist())
package_files = {name for name in wheel_names if name.startswith("agentcommunity/")}
assert package_files == expected_package_files, (
    f"unexpected wheel package files: {sorted(package_files ^ expected_package_files)}"
)
assert not any("tests" in PurePosixPath(name).parts for name in wheel_names)
assert not any(name.endswith("entry_points.txt") for name in wheel_names)
assert all(
    name.startswith("agentcommunity/") or ".dist-info/" in name
    for name in wheel_names
), f"unexpected top-level wheel content: {sorted(wheel_names)}"
PY

verify_install() {
  local artifact="$1"
  local environment="$2"
  "$python_bin" -m venv "$environment"
  "$environment/bin/python" -m pip install --disable-pip-version-check "$artifact"
  (
    cd "$temp_dir"
    "$environment/bin/python" - <<'PY'
from importlib.metadata import distribution, version
from importlib.resources import files

import agentcommunity
from agentcommunity import AgentCommunityClient, CommunityStats

expected = [
    "__version__",
    "AgentCommunityClient",
    "CommunityStats",
    "MemberMatch",
    "MemberLookup",
    "CertificateVerification",
    "AgentCommunityError",
    "AgentCommunityTransportError",
    "AgentCommunityProtocolError",
    "AgentCommunityToolError",
]
assert agentcommunity.__all__ == expected
assert agentcommunity.__version__ == "0.1.0"
assert version("agentcommunity") == "0.1.0"
assert files("agentcommunity").joinpath("py.typed").is_file()

metadata = distribution("agentcommunity").metadata
assert metadata["Requires-Python"] == ">=3.10"
assert metadata["License-Expression"] == "MIT"
assert set(metadata.get_all("Requires-Dist") or ()) >= {
    "jsonschema<5,>=4.20",
    "mcp<3,>=2.1.1",
    "pydantic<3,>=2.12",
}
assert set(metadata.get_all("Project-URL") or ()) == {
    "Homepage, https://agentcommunity.org",
    "Documentation, https://agentcommunity.org/mcp/docs",
    "Source, https://github.com/agentcommunity/agentcommunity-python",
    "Issues, https://github.com/agentcommunity/agentcommunity-python/issues",
}

client = AgentCommunityClient(endpoint="http://127.0.0.1:9/mcp", timeout=1.0)
assert client.endpoint == "http://127.0.0.1:9/mcp"
assert client.timeout == 1.0
stats = CommunityStats(member_count=0, note="offline artifact check")
assert stats.member_count == 0
PY
  )
}

verify_install "$wheel" "$temp_dir/wheel-venv"
verify_install "$sdist" "$temp_dir/sdist-venv"

echo "verified wheel and sdist: $artifact_dir"
