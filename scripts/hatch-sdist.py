from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import (  # type: ignore[import-not-found]
    BuildHookInterface,
)


class CustomBuildHook(BuildHookInterface):  # type: ignore[misc]
    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        del version
        gitignore = str(Path(self.root) / ".gitignore")
        build_data["force_include"].pop(gitignore, None)
