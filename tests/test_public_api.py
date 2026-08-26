from __future__ import annotations

import importlib.metadata
from pathlib import Path

import tomllib  # type: ignore[import-untyped]

import agentcommunity

EXPECTED_PUBLIC_API = [
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


def test_public_api_is_exactly_the_approved_read_only_surface() -> None:
    assert agentcommunity.__all__ == EXPECTED_PUBLIC_API
    assert not hasattr(agentcommunity.AgentCommunityClient, "register_agent")

    forbidden_names = {
        "Client",
        "MCPClient",
        "Session",
        "SyncAgentCommunityClient",
        "community_stats",
        "lookup_member",
        "register_agent",
        "verify_certificate",
    }
    assert forbidden_names.isdisjoint(agentcommunity.__all__)


def test_project_metadata_matches_the_official_package_contract() -> None:
    project_root = Path(__file__).parents[1]
    with (project_root / "pyproject.toml").open("rb") as metadata_file:
        pyproject = tomllib.load(metadata_file)

    project = pyproject["project"]
    assert project["requires-python"] == ">=3.10"
    assert project["license"] == "MIT"
    assert project["readme"] == "README.md"
    assert project["dependencies"] == [
        "jsonschema>=4.20,<5",
        "mcp>=2.1.1,<3",
        "pydantic>=2.12,<3",
    ]
    assert project["urls"] == {
        "Homepage": "https://agentcommunity.org",
        "Documentation": "https://agentcommunity.org/mcp/docs",
        "Source": "https://github.com/agentcommunity/agentcommunity-python",
        "Issues": "https://github.com/agentcommunity/agentcommunity-python/issues",
    }
    assert "Typing :: Typed" in project["classifiers"]
    assert "scripts" not in project

    package_root = project_root / "src" / "agentcommunity"
    assert (package_root / "py.typed").is_file()
    assert importlib.metadata.version("agentcommunity") == agentcommunity.__version__
