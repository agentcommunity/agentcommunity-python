from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anyio
import pytest
from mcp import Client
from mcp.server.mcpserver import MCPServer

from agentcommunity import (
    AgentCommunityClient,
    CertificateVerification,
    CommunityStats,
    MemberLookup,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_real_mcp_client_executes_all_three_typed_methods_on_one_connection() -> (
    None
):
    cleanup_complete = anyio.Event()

    @asynccontextmanager
    async def lifespan(server: MCPServer[None]) -> AsyncIterator[None]:
        del server
        try:
            yield None
        finally:
            cleanup_complete.set()

    server = MCPServer("typed-read-only-tools", lifespan=lifespan)
    calls: list[tuple[str, dict[str, str]]] = []

    @server.tool(name="get_community_stats", structured_output=True)
    def get_community_stats() -> dict[str, object]:
        calls.append(("get_community_stats", {}))
        return {"member_count": 29_700, "note": "Verified members"}

    @server.tool(name="lookup_member", structured_output=True)
    def lookup_member(query: str) -> dict[str, object]:
        calls.append(("lookup_member", {"query": query}))
        return {
            "status": "member",
            "matches": [
                {
                    "display_name": query,
                    "member_since": "2026-08-27",
                    "profile_url": "https://agentcommunity.org/m/example-agent",
                }
            ],
        }

    @server.tool(name="verify_certificate", structured_output=True)
    def verify_certificate(certificate_id: str) -> dict[str, object]:
        calls.append(("verify_certificate", {"certificate_id": certificate_id}))
        return {
            "certificate_id": certificate_id,
            "status": "issued",
            "valid_format": True,
            "issued": True,
            "agent_name": "Example Agent",
            "certificate_url": "https://agentcommunity.org/certificates/MESA-DD6-660J",
        }

    @server.tool(name="unrelated_tool", structured_output=True)
    def unrelated_tool() -> dict[str, bool]:
        return {"ignored": True}

    connection_count = 0

    def factory(endpoint: str, timeout: float) -> Client:
        nonlocal connection_count
        del endpoint
        connection_count += 1
        return Client(server, read_timeout_seconds=timeout)

    sdk = AgentCommunityClient(_client_factory=factory)
    async with sdk:
        stats = await sdk.community_stats()
        lookup = await sdk.lookup_member(" Example Agent ")
        certificate = await sdk.verify_certificate("MESA-DD6-660J")

    assert isinstance(stats, CommunityStats)
    assert isinstance(lookup, MemberLookup)
    assert isinstance(certificate, CertificateVerification)
    assert calls == [
        ("get_community_stats", {}),
        ("lookup_member", {"query": "Example Agent"}),
        ("verify_certificate", {"certificate_id": "MESA-DD6-660J"}),
    ]
    assert connection_count == 1
    assert cleanup_complete.is_set()
