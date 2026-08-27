from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from fakes import FakeMCPClient, RecordingClientFactory, successful_result

from agentcommunity import (
    AgentCommunityClient,
    AgentCommunityProtocolError,
    CertificateVerification,
    CommunityStats,
    MemberLookup,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_community_stats_calls_exact_tool_and_returns_model() -> None:
    fake = FakeMCPClient()
    fake.results = [successful_result({"member_count": 29_700, "note": "members"})]
    client = AgentCommunityClient(_client_factory=RecordingClientFactory(lambda: fake))

    async with client:
        result = await client.community_stats()

    assert result == CommunityStats(member_count=29_700, note="members")
    assert fake.calls == [("get_community_stats", {})]


@pytest.mark.anyio
async def test_lookup_member_trims_query_and_returns_model() -> None:
    fake = FakeMCPClient()
    fake.results = [
        successful_result(
            {
                "status": "member",
                "matches": [
                    {
                        "display_name": "Example Agent",
                        "member_since": "2026-08-27",
                        "profile_url": "https://agentcommunity.org/m/example-agent",
                    }
                ],
            }
        )
    ]
    client = AgentCommunityClient(_client_factory=RecordingClientFactory(lambda: fake))

    async with client:
        result = await client.lookup_member("  Example Agent  ")

    assert isinstance(result, MemberLookup)
    assert result.status == "member"
    assert fake.calls == [("lookup_member", {"query": "Example Agent"})]


@pytest.mark.anyio
@pytest.mark.parametrize("length", [1, 200])
async def test_lookup_member_accepts_boundary_lengths(length: int) -> None:
    fake = FakeMCPClient()
    fake.results = [successful_result({"status": "not_found", "matches": []})]
    client = AgentCommunityClient(_client_factory=RecordingClientFactory(lambda: fake))
    query = "q" * length

    async with client:
        await client.lookup_member(f" {query} ")

    assert fake.calls == [("lookup_member", {"query": query})]


@pytest.mark.anyio
@pytest.mark.parametrize("query", ["", "   ", "q" * 201, None, 123, ["agent"]])
async def test_lookup_member_rejects_invalid_input_before_transport(
    query: object,
) -> None:
    factory = RecordingClientFactory()
    client = AgentCommunityClient(_client_factory=factory)

    with pytest.raises(ValueError):
        await client.lookup_member(query)  # type: ignore[arg-type]

    assert factory.clients == []


CERTIFICATE_STATES: dict[str, dict[str, object]] = {
    "invalid_format": {
        "valid_format": False,
        "issued": False,
        "agent_name": None,
        "certificate_url": None,
    },
    "not_found": {
        "valid_format": True,
        "issued": False,
        "agent_name": None,
        "certificate_url": None,
    },
    "issued": {
        "valid_format": True,
        "issued": True,
        "agent_name": "Example Agent",
        "certificate_url": "https://agentcommunity.org/certificates/MESA-DD6-660J",
    },
    "unavailable": {
        "valid_format": True,
        "issued": None,
        "agent_name": None,
        "certificate_url": None,
    },
}


@pytest.mark.anyio
@pytest.mark.parametrize("status", CERTIFICATE_STATES)
async def test_verify_certificate_returns_every_typed_state(status: str) -> None:
    fake = FakeMCPClient()
    fake.results = [
        successful_result(
            {
                "certificate_id": "MESA-DD6-660J",
                "status": status,
                **CERTIFICATE_STATES[status],
            }
        )
    ]
    client = AgentCommunityClient(_client_factory=RecordingClientFactory(lambda: fake))

    async with client:
        result = await client.verify_certificate("MESA-DD6-660J")

    assert isinstance(result, CertificateVerification)
    assert result.status == status


@pytest.mark.anyio
@pytest.mark.parametrize("certificate_id", ["", "   ", "not-a-certificate", " X "])
async def test_verify_certificate_passes_every_string_unchanged(
    certificate_id: str,
) -> None:
    fake = FakeMCPClient()
    fake.results = [
        successful_result(
            {
                "certificate_id": certificate_id,
                "status": "invalid_format",
                **CERTIFICATE_STATES["invalid_format"],
            }
        )
    ]
    client = AgentCommunityClient(_client_factory=RecordingClientFactory(lambda: fake))

    async with client:
        result = await client.verify_certificate(certificate_id)

    assert result.certificate_id == certificate_id
    assert fake.calls == [("verify_certificate", {"certificate_id": certificate_id})]


@pytest.mark.anyio
async def test_verify_certificate_rejects_non_string_before_transport() -> None:
    factory = RecordingClientFactory()
    client = AgentCommunityClient(_client_factory=factory)

    with pytest.raises(ValueError):
        await client.verify_certificate(123)  # type: ignore[arg-type]

    assert factory.clients == []


@pytest.mark.anyio
@pytest.mark.parametrize(
    "invoke",
    [
        pytest.param(lambda client: client.community_stats(), id="community-stats"),
        pytest.param(lambda client: client.lookup_member("agent"), id="lookup-member"),
        pytest.param(
            lambda client: client.verify_certificate("bad"), id="verify-certificate"
        ),
    ],
)
async def test_each_method_translates_malformed_output_to_protocol_error(
    invoke: Callable[[AgentCommunityClient], Awaitable[Any]],
) -> None:
    fake = FakeMCPClient()
    fake.results = [successful_result({"unexpected": True})]
    client = AgentCommunityClient(_client_factory=RecordingClientFactory(lambda: fake))

    async with client:
        with pytest.raises(AgentCommunityProtocolError):
            await invoke(client)


def test_client_exposes_only_the_approved_high_level_surface() -> None:
    client = AgentCommunityClient()

    for forbidden_name in (
        "register_agent",
        "client",
        "session",
        "sync",
        "call_tool",
        "one_shot",
    ):
        assert not hasattr(client, forbidden_name)
