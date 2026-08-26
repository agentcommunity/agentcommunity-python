import os
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

import pytest


@pytest.fixture(scope="module")
def built_artifacts(tmp_path_factory: pytest.TempPathFactory) -> Path:
    artifact_dir = tmp_path_factory.mktemp("artifacts")
    subprocess.run(
        [sys.executable, "-m", "build", "--outdir", str(artifact_dir)],
        check=True,
        capture_output=True,
        text=True,
    )
    return artifact_dir


def test_sdist_excludes_local_worktree_metadata(built_artifacts: Path) -> None:
    (sdist_path,) = built_artifacts.glob("*.tar.gz")

    with tarfile.open(sdist_path, mode="r:gz") as archive:
        members = archive.getmembers()
        root = PurePosixPath(members[0].name).parts[0]
        expected_files = {
            f"{root}/CHANGELOG.md",
            f"{root}/CONTRIBUTING.md",
            f"{root}/LICENSE",
            f"{root}/PKG-INFO",
            f"{root}/README.md",
            f"{root}/SECURITY.md",
            f"{root}/pyproject.toml",
            f"{root}/src/agentcommunity/__init__.py",
            f"{root}/src/agentcommunity/_transport.py",
            f"{root}/src/agentcommunity/client.py",
            f"{root}/src/agentcommunity/errors.py",
            f"{root}/src/agentcommunity/models.py",
            f"{root}/src/agentcommunity/py.typed",
        }
        assert {member.name for member in members if member.isfile()} == expected_files
        assert all(".git" not in PurePosixPath(member.name).parts for member in members)
        assert all(
            "uv.lock" not in PurePosixPath(member.name).parts for member in members
        )
        assert all(
            "tests" not in PurePosixPath(member.name).parts for member in members
        )

        for member in members:
            if not member.isfile():
                continue
            extracted = archive.extractfile(member)
            assert extracted is not None
            contents = extracted.read()
            assert re.search(rb"gitdir:\s*(?:/|[A-Za-z]:[\\/])", contents) is None


def test_verifier_fails_closed_when_python_optimization_is_enabled(
    built_artifacts: Path, tmp_path: Path
) -> None:
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    result = subprocess.run(
        [
            "bash",
            "scripts/verify-artifacts.sh",
            str(built_artifacts),
            str(wheelhouse),
        ],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONOPTIMIZE": "1"},
        timeout=30,
    )

    assert result.returncode != 0
    assert "PYTHONOPTIMIZE" in result.stderr


def test_verifier_rejects_an_extra_mandatory_runtime_dependency(
    built_artifacts: Path, tmp_path: Path
) -> None:
    mutated_dir = tmp_path / "mutated"
    shutil.copytree(built_artifacts, mutated_dir)
    (wheel_path,) = mutated_dir.glob("*.whl")
    rewritten_path = tmp_path / "rewritten.whl"

    with (
        zipfile.ZipFile(wheel_path, mode="r") as source,
        zipfile.ZipFile(rewritten_path, mode="w") as destination,
    ):
        for member in source.infolist():
            data = source.read(member.filename)
            if member.filename.endswith(".dist-info/METADATA"):
                header, body = data.split(b"\n\n", maxsplit=1)
                data = header + b"\nRequires-Dist: typing-extensions>=4\n\n" + body
            destination.writestr(member, data)
    rewritten_path.replace(wheel_path)
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()

    result = subprocess.run(
        [
            "bash",
            "scripts/verify-artifacts.sh",
            str(mutated_dir),
            str(wheelhouse),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode != 0
    assert "mandatory Requires-Dist mismatch" in result.stderr


def test_verifier_uses_only_an_explicit_wheelhouse_and_rejects_an_empty_one(
    built_artifacts: Path, tmp_path: Path
) -> None:
    wheelhouse = tmp_path / "empty-wheelhouse"
    wheelhouse.mkdir()

    result = subprocess.run(
        [
            "bash",
            "scripts/verify-artifacts.sh",
            str(built_artifacts),
            str(wheelhouse),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode != 0
    assert "wheelhouse is incomplete" in result.stderr
    verifier = Path("scripts/verify-artifacts.sh").read_text()
    assert "--no-index" in verifier
    assert "--find-links" in verifier


def test_verifier_rejects_divergent_wheel_and_sdist_package_sources(
    built_artifacts: Path, tmp_path: Path
) -> None:
    mutated_dir = tmp_path / "divergent"
    shutil.copytree(built_artifacts, mutated_dir)
    (wheel_path,) = mutated_dir.glob("*.whl")
    rewritten_path = tmp_path / "divergent.whl"

    with (
        zipfile.ZipFile(wheel_path, mode="r") as source,
        zipfile.ZipFile(rewritten_path, mode="w") as destination,
    ):
        for member in source.infolist():
            data = source.read(member.filename)
            if member.filename == "agentcommunity/py.typed":
                data = b"divergent\n"
            destination.writestr(member, data)
    rewritten_path.replace(wheel_path)
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()

    result = subprocess.run(
        [
            "bash",
            "scripts/verify-artifacts.sh",
            str(mutated_dir),
            str(wheelhouse),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode != 0
    assert "wheel/sdist source mismatch" in result.stderr
