from __future__ import annotations

import re
from pathlib import Path

# Audited against each official repository with ``git ls-remote``. Annotated
# tags use their peeled ``^{}`` commit, never the tag-object SHA.
AUDITED_ACTION_PINS = {
    "actions/checkout": ("3d3c42e5aac5ba805825da76410c181273ba90b1", "v7.0.1"),
    "actions/setup-python": ("5fda3b95a4ea91299a34e894583c3862153e4b97", "v7.0.0"),
    "actions/upload-artifact": (
        "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
        "v7.0.1",
    ),
    "actions/download-artifact": (
        "3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c",
        "v8.0.1",
    ),
    "pypa/gh-action-pypi-publish": (
        "dc37677b2e1c63e2034f94d8a5b11f265b73ba33",
        "v1.14.2",
    ),
}


def test_every_third_party_action_is_pinned_to_a_full_commit_sha() -> None:
    workflow_root = Path(".github/workflows")
    uses_pattern = re.compile(
        r"^\s*-?\s*uses:\s*([^\s#]+)(?:\s+#\s*(.+))?$", re.MULTILINE
    )

    found_actions: set[str] = set()
    for workflow in workflow_root.glob("*.yml"):
        for reference, comment in uses_pattern.findall(workflow.read_text()):
            if reference.startswith("./"):
                continue
            match = re.fullmatch(r"([^/@]+/[^/@]+)@([0-9a-f]{40})", reference)
            assert match is not None, (
                f"unpinned third-party action in {workflow}: {reference}"
            )
            assert re.fullmatch(r"v?[0-9]+(?:\.[0-9]+){1,2}", comment.strip()), (
                f"missing human release comment for {reference} in {workflow}"
            )
            action, commit_sha = match.groups()
            found_actions.add(action)
            assert action in AUDITED_ACTION_PINS, (
                f"unaudited third-party action in {workflow}: {action}"
            )
            expected_sha, expected_tag = AUDITED_ACTION_PINS[action]
            assert (commit_sha, comment.strip()) == (expected_sha, expected_tag), (
                f"pin for {action} in {workflow} does not match its audited "
                f"{expected_tag} commit"
            )

    assert found_actions == set(AUDITED_ACTION_PINS)
