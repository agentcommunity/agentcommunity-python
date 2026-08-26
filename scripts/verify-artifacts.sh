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
from email.parser import BytesParser
from pathlib import PurePosixPath

from packaging.requirements import Requirement

if sys.flags.optimize:
    raise SystemExit("PYTHONOPTIMIZE must be disabled for artifact verification")

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


def validate_runtime_requirements(archive_path: str, metadata_bytes: bytes) -> None:
    metadata = BytesParser().parsebytes(metadata_bytes)
    requirements = {
        Requirement(value)
        for value in metadata.get_all("Requires-Dist", [])
        if "extra" not in str(Requirement(value).marker)
    }
    expected = {
        Requirement("jsonschema>=4.20,<5"),
        Requirement("mcp>=2.1.1,<3"),
        Requirement("pydantic>=2.12,<3"),
    }
    if requirements != expected:
        raise SystemExit(
            "mandatory Requires-Dist mismatch in "
            f"{archive_path}: got {sorted(map(str, requirements))}"
        )


with zipfile.ZipFile(wheel_path) as archive:
    wheel_metadata = [
        name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
    ]
    assert len(wheel_metadata) == 1
    validate_runtime_requirements(wheel_path, archive.read(wheel_metadata[0]))
    for name in archive.namelist():
        validate_name(wheel_path, name)
        if not name.endswith("/"):
            validate_contents(wheel_path, name, archive.read(name))

with tarfile.open(sdist_path, mode="r:gz") as archive:
    sdist_metadata = [
        member for member in archive.getmembers() if member.name.endswith("/PKG-INFO")
    ]
    assert len(sdist_metadata) == 1
    extracted_metadata = archive.extractfile(sdist_metadata[0])
    assert extracted_metadata is not None
    validate_runtime_requirements(sdist_path, extracted_metadata.read())
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
import asyncio
import sys
from types import TracebackType
from typing import Any

import agentcommunity
from agentcommunity import AgentCommunityClient, CommunityStats
from mcp.types import CallToolResult

if sys.flags.optimize:
    raise SystemExit("PYTHONOPTIMIZE must be disabled for artifact verification")

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


class OfflineMCPClient:
    def __init__(self) -> None:
        self.enter_count = 0
        self.exit_count = 0
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def __aenter__(self) -> "OfflineMCPClient":
        self.enter_count += 1
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        self.exit_count += 1

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        read_timeout_seconds: float | None = None,
    ) -> CallToolResult:
        assert read_timeout_seconds == 1.0
        self.calls.append((name, arguments or {}))
        return CallToolResult(
            content=[],
            structured_content={
                "member_count": 0,
                "note": "offline artifact check",
            },
        )


offline_client = OfflineMCPClient()


def offline_factory(endpoint: str, timeout: float) -> OfflineMCPClient:
    assert endpoint == "http://127.0.0.1:9/mcp"
    assert timeout == 1.0
    return offline_client


async def verify_offline_behavior() -> None:
    client = AgentCommunityClient(
        endpoint="http://127.0.0.1:9/mcp",
        timeout=1.0,
        _client_factory=offline_factory,
    )
    async with client:
        stats = await client.community_stats()
    assert isinstance(stats, CommunityStats)
    assert stats.member_count == 0
    assert stats.note == "offline artifact check"


asyncio.run(verify_offline_behavior())
assert offline_client.enter_count == 1
assert offline_client.exit_count == 1
assert offline_client.calls == [("get_community_stats", {})]
PY
  )
}

verify_install "$wheel" "$temp_dir/wheel-venv"
verify_install "$sdist" "$temp_dir/sdist-venv"

echo "verified wheel and sdist: $artifact_dir"
