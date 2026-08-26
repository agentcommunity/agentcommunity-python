from __future__ import annotations

import re
from pathlib import Path

import pytest
from fakes import FakeMCPClient, RecordingClientFactory
from mcp.types import CallToolResult


def _inject_offline_factory(code: str) -> str:
    constructor = "AgentCommunityClient()"
    assert code.count(constructor) == 1, (
        "README main example must contain exactly one injectable default constructor"
    )
    return code.replace(
        constructor,
        "AgentCommunityClient(_client_factory=readme_test_factory)",
        1,
    )


def test_readme_injection_fails_closed_when_constructor_target_drifts() -> None:
    with pytest.raises(AssertionError, match="exactly one injectable"):
        _inject_offline_factory("AgentCommunityClient(timeout=10.0)")


def test_readme_main_example_runs_against_an_offline_transport(
    capsys: pytest.CaptureFixture[str],
) -> None:
    readme = (Path(__file__).parents[1] / "README.md").read_text()
    match = re.search(
        r"<!-- main-example:start -->\s*```python\n(?P<code>.*?)\n```\s*"
        r"<!-- main-example:end -->",
        readme,
        flags=re.DOTALL,
    )
    assert match is not None

    factory = RecordingClientFactory()
    client = factory.clients
    code = _inject_offline_factory(match.group("code"))

    original_call = factory

    def configured_factory(endpoint: str, timeout: float) -> FakeMCPClient:
        fake = original_call(endpoint, timeout)
        fake.results.extend(
            [
                CallToolResult(
                    content=[],
                    structured_content={
                        "member_count": 29_700,
                        "note": "Verified members",
                    },
                ),
                CallToolResult(
                    content=[],
                    structured_content={
                        "status": "member",
                        "matches": [
                            {
                                "display_name": "Example Agent",
                                "member_since": "2026-08-27",
                                "profile_url": (
                                    "https://agentcommunity.org/m/example-agent"
                                ),
                            }
                        ],
                    },
                ),
                CallToolResult(
                    content=[],
                    structured_content={
                        "certificate_id": "MESA-DD6-660J",
                        "status": "issued",
                        "valid_format": True,
                        "issued": True,
                        "agent_name": "Example Agent",
                        "certificate_url": (
                            "https://agentcommunity.org/certificates/MESA-DD6-660J"
                        ),
                    },
                ),
            ]
        )
        return fake

    namespace = {
        "__name__": "__main__",
        "readme_test_factory": configured_factory,
    }
    exec(compile(code, "README.md", "exec"), namespace)

    assert len(client) == 1
    assert client[0].calls == [
        ("get_community_stats", {}),
        ("lookup_member", {"query": "Example Agent"}),
        ("verify_certificate", {"certificate_id": "MESA-DD6-660J"}),
    ]
    assert "29700" in capsys.readouterr().out
