from __future__ import annotations

import re
from pathlib import Path


def test_every_third_party_action_is_pinned_to_a_full_commit_sha() -> None:
    workflow_root = Path(".github/workflows")
    uses_pattern = re.compile(
        r"^\s*-?\s*uses:\s*([^\s#]+)(?:\s+#\s*(.+))?$", re.MULTILINE
    )

    found = 0
    for workflow in workflow_root.glob("*.yml"):
        for reference, comment in uses_pattern.findall(workflow.read_text()):
            if reference.startswith("./"):
                continue
            found += 1
            assert re.fullmatch(r"[^/@]+/[^/@]+@[0-9a-f]{40}", reference), (
                f"unpinned third-party action in {workflow}: {reference}"
            )
            assert re.fullmatch(r"v?[0-9]+(?:\.[0-9]+){1,2}", comment.strip()), (
                f"missing human release comment for {reference} in {workflow}"
            )

    assert found > 0
