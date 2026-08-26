from __future__ import annotations

import subprocess
import sys

import pytest


def run_release_check(tag: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/check-release-tag.py", tag, "pyproject.toml"],
        check=False,
        capture_output=True,
        text=True,
    )


def test_release_tag_must_exactly_match_project_version() -> None:
    result = run_release_check("v0.1.0")

    assert result.returncode == 0


@pytest.mark.parametrize("tag", ["vbanana", "v0.2.0", "v0.1.0-typo"])
def test_release_tag_rejects_nonmatching_or_malformed_values(tag: str) -> None:
    result = run_release_check(tag)

    assert result.returncode != 0
    assert "release tag mismatch" in result.stderr
