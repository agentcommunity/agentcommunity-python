from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, cast

import anyio
import mcp_types as types
import pytest
from jsonschema.exceptions import (  # type: ignore[import-untyped]
    ValidationError as JsonSchemaValidationError,
)
from mcp import Client, MCPError
from mcp.server import Server, ServerRequestContext
from mcp.server.mcpserver import MCPServer

from agentcommunity import (
    AgentCommunityClient,
    AgentCommunityProtocolError,
    AgentCommunityTransportError,
)
from agentcommunity.models import CommunityStats


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_real_client_lifecycle_call_and_slow_cleanup_are_clean() -> None:
    cleanup_complete = anyio.Event()

    @asynccontextmanager
    async def lifespan(
        server: MCPServer[None],
    ) -> AsyncIterator[None]:
        del server
        try:
            yield None
        finally:
            await anyio.sleep(0.03)
            cleanup_complete.set()

    server = MCPServer("real-lifecycle", lifespan=lifespan)

    @server.tool()
    def stats() -> dict[str, object]:
        return {"member_count": 1, "note": "real stack"}

    clients: list[Client] = []

    def factory(endpoint: str, timeout: float) -> Client:
        del endpoint
        client = Client(server, read_timeout_seconds=timeout)
        clients.append(client)
        return client

    sdk = AgentCommunityClient(timeout=0.01, _client_factory=factory)
    async with sdk:
        result = await sdk._call_typed("stats", {}, CommunityStats)

    assert result == CommunityStats(member_count=1, note="real stack")
    assert cleanup_complete.is_set()
    assert clients[0]._session is None
    exit_stack = cast(Any, clients[0]._exit_stack)
    assert not exit_stack._exit_callbacks


@pytest.mark.anyio
async def test_real_stalled_initialization_times_out_and_cleans_up() -> None:
    initialize_started = anyio.Event()
    initialize_cancelled = anyio.Event()

    async def stall_initialize(
        context: ServerRequestContext[Any, Any],
        call_next: Callable[[ServerRequestContext[Any, Any]], Awaitable[Any]],
    ) -> Any:
        if context.method == "initialize":
            initialize_started.set()
            try:
                await anyio.Event().wait()
            except anyio.get_cancelled_exc_class():
                initialize_cancelled.set()
                raise
        return await call_next(context)

    server = Server("stalled-initialize")
    server.middleware.append(cast(Any, stall_initialize))
    clients: list[Client] = []

    def factory(endpoint: str, timeout: float) -> Client:
        del endpoint
        client = Client(server, mode="legacy", read_timeout_seconds=timeout)
        clients.append(client)
        return client

    sdk = AgentCommunityClient(timeout=0.01, _client_factory=factory)
    with pytest.raises(
        AgentCommunityTransportError, match=r"connect.*0\.01"
    ) as captured:
        await sdk.__aenter__()

    assert isinstance(captured.value.__cause__, TimeoutError)
    assert initialize_started.is_set()
    assert initialize_cancelled.is_set()
    assert clients[0]._session is None
    assert clients[0]._exit_stack is None
    with anyio.fail_after(1):
        await anyio.lowlevel.checkpoint()


@pytest.mark.anyio
async def test_real_native_call_timeout_leaves_connection_usable() -> None:
    async def list_tools(
        context: ServerRequestContext[Any, Any],
        params: types.PaginatedRequestParams | None,
    ) -> types.ListToolsResult:
        del context, params
        return types.ListToolsResult(
            tools=[
                types.Tool(name="block", input_schema={"type": "object"}),
                types.Tool(name="stats", input_schema={"type": "object"}),
            ]
        )

    async def call_tool(
        context: ServerRequestContext[Any, Any],
        params: types.CallToolRequestParams,
    ) -> types.CallToolResult:
        del context
        if params.name == "block":
            await anyio.Event().wait()
            raise AssertionError("unreachable")
        return types.CallToolResult(
            content=[],
            structured_content={"member_count": 2, "note": "still usable"},
        )

    server = Server(
        "native-call-timeout", on_list_tools=list_tools, on_call_tool=call_tool
    )

    def factory(endpoint: str, timeout: float) -> Client:
        del endpoint
        return Client(server, mode="legacy", read_timeout_seconds=timeout)

    sdk = AgentCommunityClient(timeout=0.01, _client_factory=factory)
    async with sdk:
        with pytest.raises(
            AgentCommunityTransportError, match=r"block.*0\.01"
        ) as captured:
            await sdk._call_typed("block", {}, CommunityStats)
        result = await sdk._call_typed("stats", {}, CommunityStats)

    assert isinstance(captured.value.__cause__, MCPError)
    assert result.member_count == 2


@pytest.mark.anyio
async def test_real_output_schema_mismatch_is_protocol_error() -> None:
    async def list_tools(
        context: ServerRequestContext[Any, Any],
        params: types.PaginatedRequestParams | None,
    ) -> types.ListToolsResult:
        del context, params
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name="bad",
                    input_schema={"type": "object"},
                    output_schema={
                        "type": "object",
                        "properties": {"member_count": {"type": "integer"}},
                        "required": ["member_count"],
                    },
                )
            ]
        )

    async def call_tool(
        context: ServerRequestContext[Any, Any],
        params: types.CallToolRequestParams,
    ) -> types.CallToolResult:
        del context, params
        return types.CallToolResult(
            content=[], structured_content={"member_count": "many"}
        )

    server = Server("schema-mismatch", on_list_tools=list_tools, on_call_tool=call_tool)

    def factory(endpoint: str, timeout: float) -> Client:
        del endpoint
        return Client(server, mode="legacy", read_timeout_seconds=timeout)

    sdk = AgentCommunityClient(_client_factory=factory)
    async with sdk:
        with pytest.raises(AgentCommunityProtocolError) as captured:
            await sdk._call_typed("bad", {}, CommunityStats)

    upstream = captured.value.__cause__
    assert isinstance(upstream, RuntimeError)
    assert isinstance(upstream.__cause__, JsonSchemaValidationError)
