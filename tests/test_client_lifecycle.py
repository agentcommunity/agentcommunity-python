from __future__ import annotations

import asyncio
import math

import pytest
from fakes import FakeMCPClient, RecordingClientFactory, successful_result

from agentcommunity import (
    AgentCommunityClient,
    AgentCommunityProtocolError,
    AgentCommunityTransportError,
)
from agentcommunity.models import CommunityStats


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_default_and_overridden_configuration() -> None:
    default_client = AgentCommunityClient()
    overridden_client = AgentCommunityClient(
        endpoint="http://localhost:8765/mcp?tenant=test", timeout=2
    )

    assert default_client.endpoint == "https://agentcommunity.org/mcp"
    assert default_client.timeout == 15.0
    assert overridden_client.endpoint == "http://localhost:8765/mcp?tenant=test"
    assert overridden_client.timeout == 2.0


@pytest.mark.parametrize(
    "endpoint",
    [
        None,
        123,
        "",
        " agentcommunity.org/mcp",
        "agentcommunity.org/mcp",
        "ftp://agentcommunity.org/mcp",
        "https:///mcp",
        "https://user:secret@agentcommunity.org/mcp",
        "https://agentcommunity.org/mcp#fragment",
        "https://agent community.org/mcp",
        "https://%zz/mcp",
        "https://example.com/%zz",
        "https://example.com/mcp?cursor=%0x",
    ],
)
def test_invalid_endpoints_fail_locally(endpoint: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        AgentCommunityClient(endpoint=endpoint)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "timeout", [None, True, "15", 0, -1, math.inf, -math.inf, math.nan]
)
def test_invalid_timeouts_fail_locally(timeout: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        AgentCommunityClient(timeout=timeout)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://%65xample.com/mcp",
        "https://example.com/a%20path",
        "https://example.com/mcp?cursor=a%2Fb",
    ],
)
def test_valid_percent_escapes_are_preserved(endpoint: str) -> None:
    client = AgentCommunityClient(endpoint=endpoint)

    assert client.endpoint == endpoint


@pytest.mark.anyio
async def test_context_opens_and_closes_exactly_one_underlying_client() -> None:
    factory = RecordingClientFactory()
    client = AgentCommunityClient(_client_factory=factory)

    async with client as entered:
        assert entered is client
        assert len(factory.clients) == 1
        assert factory.clients[0].enter_count == 1

    assert factory.endpoints == ["https://agentcommunity.org/mcp"]
    assert factory.clients[0].exit_count == 1


@pytest.mark.anyio
async def test_one_connection_supports_multiple_sequential_calls() -> None:
    fake = FakeMCPClient()
    fake.results = [
        successful_result({"member_count": 1, "note": "first"}),
        successful_result({"member_count": 2, "note": "second"}),
    ]
    factory = RecordingClientFactory(lambda: fake)
    client = AgentCommunityClient(_client_factory=factory)

    async with client:
        first = await client._call_typed("first", {}, CommunityStats)
        second = await client._call_typed("second", {}, CommunityStats)

    assert (first.member_count, second.member_count) == (1, 2)
    assert fake.enter_count == 1
    assert fake.exit_count == 1
    assert fake.calls == [("first", {}), ("second", {})]


@pytest.mark.anyio
async def test_calls_outside_context_raise_protocol_error() -> None:
    client = AgentCommunityClient(_client_factory=RecordingClientFactory())

    with pytest.raises(AgentCommunityProtocolError, match="active context"):
        await client._call_typed("before", {}, CommunityStats)

    async with client:
        pass

    with pytest.raises(AgentCommunityProtocolError, match="active context"):
        await client._call_typed("after", {}, CommunityStats)


@pytest.mark.anyio
async def test_reentering_active_client_fails_predictably() -> None:
    client = AgentCommunityClient(_client_factory=RecordingClientFactory())

    async with client:
        with pytest.raises(AgentCommunityProtocolError, match="already active"):
            await client.__aenter__()


@pytest.mark.anyio
async def test_simultaneous_entry_cannot_open_two_clients() -> None:
    fake = FakeMCPClient()
    fake.connect_gate = asyncio.Event()
    factory = RecordingClientFactory(lambda: fake)
    client = AgentCommunityClient(_client_factory=factory)
    entered = asyncio.Event()
    close_owner = asyncio.Event()

    async def own_lifecycle() -> None:
        await client.__aenter__()
        entered.set()
        await close_owner.wait()
        await client.close()

    owner = asyncio.create_task(own_lifecycle())
    while fake.enter_count == 0:
        await asyncio.sleep(0)

    with pytest.raises(AgentCommunityProtocolError, match="connect"):
        await client.__aenter__()

    fake.connect_gate.set()
    await entered.wait()
    assert len(factory.clients) == 1
    close_owner.set()
    await owner
    assert fake.successful_exit_count == 1


@pytest.mark.anyio
async def test_close_is_idempotent_before_and_after_context_exit() -> None:
    factory = RecordingClientFactory()
    client = AgentCommunityClient(_client_factory=factory)

    await client.close()
    await client.close()
    async with client:
        pass
    await client.close()
    await client.close()

    assert factory.clients[0].exit_count == 1


@pytest.mark.anyio
async def test_close_timeout_retains_connection_for_successful_retry() -> None:
    fake = FakeMCPClient()
    fake.close_gate = asyncio.Event()
    client = AgentCommunityClient(
        timeout=0.01, _client_factory=RecordingClientFactory(lambda: fake)
    )
    await client.__aenter__()

    with pytest.raises(AgentCommunityTransportError, match="close"):
        await client.close()

    fake.close_gate.set()
    await client.close()
    await client.close()

    assert fake.exit_count == 2
    assert fake.successful_exit_count == 1


@pytest.mark.anyio
async def test_close_failure_retains_connection_for_successful_retry() -> None:
    upstream = OSError("close failed")
    fake = FakeMCPClient()
    fake.close_error = upstream
    client = AgentCommunityClient(_client_factory=RecordingClientFactory(lambda: fake))
    await client.__aenter__()

    with pytest.raises(AgentCommunityTransportError) as captured:
        await client.close()
    assert captured.value.__cause__ is upstream
    with pytest.raises(AgentCommunityProtocolError, match="failed close"):
        await client._call_typed("get_community_stats", {}, CommunityStats)

    fake.close_error = None
    await client.close()
    await client.close()

    assert fake.exit_count == 2
    assert fake.successful_exit_count == 1


@pytest.mark.anyio
async def test_close_cancellation_retains_connection_for_successful_retry() -> None:
    fake = FakeMCPClient()
    fake.close_gate = asyncio.Event()
    client = AgentCommunityClient(_client_factory=RecordingClientFactory(lambda: fake))
    entered = asyncio.Event()
    begin_close = asyncio.Event()
    retry_close = asyncio.Event()
    cancellation_seen = asyncio.Event()

    async def own_lifecycle() -> None:
        await client.__aenter__()
        entered.set()
        await begin_close.wait()
        try:
            await client.close()
        except asyncio.CancelledError:
            cancellation_seen.set()
        await retry_close.wait()
        await client.close()

    task = asyncio.create_task(own_lifecycle())
    await entered.wait()
    begin_close.set()
    while fake.exit_count == 0:
        await asyncio.sleep(0)
    task.cancel()
    await cancellation_seen.wait()

    fake.close_gate.set()
    retry_close.set()
    await task

    assert fake.exit_count == 2
    assert fake.successful_exit_count == 1


@pytest.mark.anyio
async def test_cross_task_and_simultaneous_close_do_not_duplicate_exit() -> None:
    fake = FakeMCPClient()
    fake.close_gate = asyncio.Event()
    client = AgentCommunityClient(_client_factory=RecordingClientFactory(lambda: fake))
    entered = asyncio.Event()
    begin_close = asyncio.Event()

    async def own_lifecycle() -> None:
        await client.__aenter__()
        entered.set()
        await begin_close.wait()
        await client.close()

    owner = asyncio.create_task(own_lifecycle())
    await entered.wait()
    with pytest.raises(AgentCommunityProtocolError, match="same task"):
        await client.close()

    begin_close.set()
    while fake.exit_count == 0:
        await asyncio.sleep(0)
    with pytest.raises(AgentCommunityProtocolError, match="close"):
        await client.close()
    assert fake.exit_count == 1

    fake.close_gate.set()
    await owner
    assert fake.exit_count == 1
    assert fake.successful_exit_count == 1


@pytest.mark.anyio
async def test_tool_call_during_close_is_rejected() -> None:
    fake = FakeMCPClient()
    fake.close_gate = asyncio.Event()
    client = AgentCommunityClient(_client_factory=RecordingClientFactory(lambda: fake))
    entered = asyncio.Event()
    begin_close = asyncio.Event()

    async def own_lifecycle() -> None:
        await client.__aenter__()
        entered.set()
        await begin_close.wait()
        await client.close()

    owner = asyncio.create_task(own_lifecycle())
    await entered.wait()
    begin_close.set()
    while fake.exit_count == 0:
        await asyncio.sleep(0)

    with pytest.raises(AgentCommunityProtocolError, match="closing"):
        await client._call_typed("get_community_stats", {}, CommunityStats)

    fake.close_gate.set()
    await owner
    assert fake.calls == []


@pytest.mark.anyio
async def test_cancellation_during_connect_propagates_unchanged() -> None:
    fake = FakeMCPClient()
    fake.connect_gate = asyncio.Event()
    client = AgentCommunityClient(_client_factory=RecordingClientFactory(lambda: fake))
    task = asyncio.create_task(client.__aenter__())
    await asyncio.sleep(0)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.anyio
async def test_cancellation_during_tool_call_propagates_unchanged() -> None:
    fake = FakeMCPClient()
    fake.call_gate = asyncio.Event()
    client = AgentCommunityClient(_client_factory=RecordingClientFactory(lambda: fake))

    async with client:
        task = asyncio.create_task(client._call_typed("blocked", {}, CommunityStats))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.anyio
async def test_concurrent_tool_call_is_rejected() -> None:
    fake = FakeMCPClient()
    fake.call_gate = asyncio.Event()
    client = AgentCommunityClient(_client_factory=RecordingClientFactory(lambda: fake))

    async with client:
        first_call = asyncio.create_task(
            client._call_typed("first", {}, CommunityStats)
        )
        while not fake.calls:
            await asyncio.sleep(0)
        with pytest.raises(AgentCommunityProtocolError, match="Concurrent"):
            await client._call_typed("second", {}, CommunityStats)
        first_call.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first_call

    assert fake.calls == [("first", {})]
