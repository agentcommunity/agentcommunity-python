from __future__ import annotations

import asyncio

import pytest
from fakes import (
    FakeMCPClient,
    RecordingClientFactory,
    error_result,
    successful_result,
)
from mcp.types import CallToolResult, ImageContent, TextContent
from pydantic import ValidationError

from agentcommunity import (
    AgentCommunityClient,
    AgentCommunityProtocolError,
    AgentCommunityToolError,
    AgentCommunityTransportError,
)
from agentcommunity.models import CommunityStats


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_connection_failure_is_translated_with_cause() -> None:
    upstream = OSError("connection refused")
    fake = FakeMCPClient()
    fake.connect_error = upstream
    client = AgentCommunityClient(_client_factory=RecordingClientFactory(lambda: fake))

    with pytest.raises(AgentCommunityTransportError, match="connect") as captured:
        await client.__aenter__()

    assert captured.value.__cause__ is upstream


@pytest.mark.anyio
async def test_tool_transport_failure_is_translated_with_cause() -> None:
    upstream = RuntimeError("MCP stream ended")
    fake = FakeMCPClient()
    fake.call_error = upstream
    client = AgentCommunityClient(_client_factory=RecordingClientFactory(lambda: fake))

    async with client:
        with pytest.raises(
            AgentCommunityTransportError, match="get_community_stats"
        ) as captured:
            await client._call_typed("get_community_stats", {}, CommunityStats)

    assert captured.value.__cause__ is upstream


@pytest.mark.anyio
async def test_upstream_mcp_result_validation_failure_is_protocol_error() -> None:
    with pytest.raises(ValidationError) as validation:
        CommunityStats.model_validate({"member_count": "many", "note": "bad"})
    upstream = validation.value
    fake = FakeMCPClient()
    fake.call_error = upstream
    client = AgentCommunityClient(_client_factory=RecordingClientFactory(lambda: fake))

    async with client:
        with pytest.raises(AgentCommunityProtocolError) as captured:
            await client._call_typed("get_community_stats", {}, CommunityStats)

    assert captured.value.__cause__ is upstream


@pytest.mark.anyio
async def test_connection_timeout_names_operation_and_duration() -> None:
    fake = FakeMCPClient()
    fake.connect_gate = asyncio.Event()
    client = AgentCommunityClient(
        timeout=0.01, _client_factory=RecordingClientFactory(lambda: fake)
    )

    with pytest.raises(
        AgentCommunityTransportError, match=r"connect.*0\.01"
    ) as captured:
        await client.__aenter__()

    assert isinstance(captured.value.__cause__, TimeoutError)


@pytest.mark.anyio
async def test_tool_timeout_names_operation_and_duration() -> None:
    fake = FakeMCPClient()
    fake.call_gate = asyncio.Event()
    client = AgentCommunityClient(
        timeout=0.01, _client_factory=RecordingClientFactory(lambda: fake)
    )

    async with client:
        with pytest.raises(
            AgentCommunityTransportError,
            match=r"get_community_stats.*0\.01",
        ) as captured:
            await client._call_typed("get_community_stats", {}, CommunityStats)

    assert isinstance(captured.value.__cause__, TimeoutError)


@pytest.mark.anyio
async def test_tool_error_uses_only_bounded_safe_text() -> None:
    fake = FakeMCPClient()
    fake.results = [error_result("  public\nmessage  " + "x" * 1_000)]
    client = AgentCommunityClient(_client_factory=RecordingClientFactory(lambda: fake))

    async with client:
        with pytest.raises(AgentCommunityToolError) as captured:
            await client._call_typed("get_community_stats", {}, CommunityStats)

    message = str(captured.value)
    assert "public message" in message
    assert len(message) <= 600
    assert "TextContent" not in message


@pytest.mark.anyio
async def test_tool_error_sanitizes_controls_and_bounds_multiple_blocks() -> None:
    fake = FakeMCPClient()
    fake.results = [
        CallToolResult(
            content=[
                ImageContent(data="AAAA", mime_type="image/png"),
                TextContent(text="safe\x1b[31m red\x00 nul\x9b c1"),
                TextContent(text="y" * 100_000),
                TextContent(text="must-not-appear"),
            ],
            is_error=True,
        )
    ]
    client = AgentCommunityClient(_client_factory=RecordingClientFactory(lambda: fake))

    async with client:
        with pytest.raises(AgentCommunityToolError) as captured:
            await client._call_typed("get_community_stats", {}, CommunityStats)

    message = str(captured.value)
    assert "safe [31m red nul c1" in message
    assert "\x1b" not in message
    assert "\x00" not in message
    assert "\x9b" not in message
    assert "AAAA" not in message
    assert "must-not-appear" not in message
    assert len(message) <= 600


@pytest.mark.anyio
async def test_missing_structured_content_is_protocol_error() -> None:
    fake = FakeMCPClient()
    fake.results = [successful_result(None)]
    fake.results[0].structured_content = None
    client = AgentCommunityClient(_client_factory=RecordingClientFactory(lambda: fake))

    async with client:
        with pytest.raises(AgentCommunityProtocolError, match="structured content"):
            await client._call_typed("get_community_stats", {}, CommunityStats)


@pytest.mark.anyio
async def test_model_validation_failure_is_protocol_error_with_cause() -> None:
    fake = FakeMCPClient()
    fake.results = [successful_result({"member_count": "many", "note": "bad"})]
    client = AgentCommunityClient(_client_factory=RecordingClientFactory(lambda: fake))

    async with client:
        with pytest.raises(
            AgentCommunityProtocolError, match="invalid structured"
        ) as captured:
            await client._call_typed("get_community_stats", {}, CommunityStats)

    assert isinstance(captured.value.__cause__, ValidationError)


@pytest.mark.anyio
async def test_cancelled_error_is_not_translated() -> None:
    fake = FakeMCPClient()
    fake.call_error = asyncio.CancelledError()
    client = AgentCommunityClient(_client_factory=RecordingClientFactory(lambda: fake))

    async with client:
        with pytest.raises(asyncio.CancelledError):
            await client._call_typed("get_community_stats", {}, CommunityStats)
