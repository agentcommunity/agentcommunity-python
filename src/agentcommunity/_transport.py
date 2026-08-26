from __future__ import annotations

from collections.abc import Callable
from types import TracebackType
from typing import Any, Protocol, cast

from anyio import fail_after
from mcp import Client
from mcp.types import CallToolResult

from agentcommunity.errors import (
    AgentCommunityProtocolError,
    AgentCommunityTransportError,
)


class _HighLevelClient(Protocol):
    async def __aenter__(self) -> _HighLevelClient: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> CallToolResult: ...


_ClientFactory = Callable[[str], _HighLevelClient]


def _create_mcp_client(endpoint: str) -> _HighLevelClient:
    return cast(_HighLevelClient, Client(endpoint))


class _MCPTransport:
    def __init__(
        self,
        endpoint: str,
        timeout: float,
        *,
        client_factory: _ClientFactory | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._timeout = timeout
        self._client_factory = client_factory or _create_mcp_client
        self._client: _HighLevelClient | None = None

    @property
    def active(self) -> bool:
        return self._client is not None

    async def connect(self) -> None:
        if self.active:
            raise AgentCommunityProtocolError("Client context is already active")

        try:
            client = self._client_factory(self._endpoint)
            with fail_after(self._timeout):
                await client.__aenter__()
        except TimeoutError as error:
            raise AgentCommunityTransportError(
                f"Timed out while attempting to connect after {self._timeout:g} seconds"
            ) from error
        except Exception as error:
            raise AgentCommunityTransportError(
                "Failed to connect to the Agent Community MCP endpoint"
            ) from error

        self._client = client

    async def close(
        self,
        exc_type: type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> None:
        client = self._client
        if client is None:
            return
        self._client = None

        try:
            with fail_after(self._timeout):
                await client.__aexit__(exc_type, exc_value, traceback)
        except TimeoutError as error:
            raise AgentCommunityTransportError(
                f"Timed out while attempting to close after {self._timeout:g} seconds"
            ) from error
        except Exception as error:
            raise AgentCommunityTransportError(
                "Failed to close the Agent Community MCP connection"
            ) from error

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> CallToolResult:
        client = self._client
        if client is None:
            raise AgentCommunityProtocolError(
                "Tool calls require an active context for this client"
            )

        try:
            with fail_after(self._timeout):
                return await client.call_tool(name, arguments)
        except TimeoutError as error:
            raise AgentCommunityTransportError(
                f"Tool {name!r} timed out after {self._timeout:g} seconds"
            ) from error
        except Exception as error:
            raise AgentCommunityTransportError(
                f"Failed while calling MCP tool {name!r}"
            ) from error
