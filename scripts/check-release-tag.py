from __future__ import annotations

import argparse
from pathlib import Path

try:
    import tomllib  # type: ignore[import-untyped]
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10
    import tomli as tomllib  # type: ignore[import-not-found]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Require a release tag to match project.version exactly."
    )
    parser.add_argument("tag")
    parser.add_argument("pyproject", type=Path)
    args = parser.parse_args()

    with args.pyproject.open("rb") as pyproject_file:
        project = tomllib.load(pyproject_file)["project"]
    expected = f"v{project['version']}"
    if args.tag != expected:
        parser.exit(
            1,
            f"release tag mismatch: expected {expected!r}, got {args.tag!r}\n",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
