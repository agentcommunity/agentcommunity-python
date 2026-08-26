from __future__ import annotations

from collections.abc import Callable
from enum import Enum, auto
from types import TracebackType
from typing import Any, Protocol, cast

from anyio import fail_after, get_current_task
from mcp import Client
from mcp.types import CallToolResult
from pydantic import ValidationError

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


class _LifecycleState(Enum):
    NEW = auto()
    CONNECTING = auto()
    OPEN = auto()
    CALLING = auto()
    CLOSING = auto()
    CLOSE_FAILED = auto()
    CLOSED = auto()


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
        self._state = _LifecycleState.NEW
        self._owner_task_id: int | None = None

    @property
    def active(self) -> bool:
        return self._state not in {_LifecycleState.NEW, _LifecycleState.CLOSED}

    async def connect(self) -> None:
        if self._state is _LifecycleState.CONNECTING:
            raise AgentCommunityProtocolError("Client is already connecting")
        if self._state is _LifecycleState.CLOSING:
            raise AgentCommunityProtocolError("Client is currently closing")
        if self._state is _LifecycleState.CLOSE_FAILED:
            raise AgentCommunityProtocolError(
                "Client has a failed close; retry close before reconnecting"
            )
        if self._state in {_LifecycleState.OPEN, _LifecycleState.CALLING}:
            raise AgentCommunityProtocolError("Client context is already active")

        previous_state = self._state
        self._state = _LifecycleState.CONNECTING
        self._owner_task_id = get_current_task().id
        try:
            client = self._client_factory(self._endpoint)
            with fail_after(self._timeout):
                await client.__aenter__()
        except TimeoutError as error:
            raise AgentCommunityTransportError(
                f"Timed out while attempting to connect after {self._timeout:g} seconds"
            ) from error
        except ValidationError as error:
            raise AgentCommunityProtocolError(
                "MCP initialization returned protocol-invalid data"
            ) from error
        except Exception as error:
            raise AgentCommunityTransportError(
                "Failed to connect to the Agent Community MCP endpoint"
            ) from error
        else:
            self._client = client
            self._state = _LifecycleState.OPEN
        finally:
            if self._state is _LifecycleState.CONNECTING:
                self._state = previous_state
                self._owner_task_id = None

    async def close(
        self,
        exc_type: type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> None:
        if self._state in {_LifecycleState.NEW, _LifecycleState.CLOSED}:
            return
        if self._state is _LifecycleState.CONNECTING:
            raise AgentCommunityProtocolError("Cannot close while client is connecting")
        if self._state is _LifecycleState.CALLING:
            raise AgentCommunityProtocolError(
                "Cannot close while a tool call is active"
            )
        if self._state is _LifecycleState.CLOSING:
            raise AgentCommunityProtocolError("Client close is already in progress")
        if get_current_task().id != self._owner_task_id:
            raise AgentCommunityProtocolError(
                "Client must be closed in the same task that entered it"
            )

        client = self._client
        if client is None:
            raise AgentCommunityProtocolError("Client lifecycle state is inconsistent")
        self._state = _LifecycleState.CLOSING

        try:
            with fail_after(self._timeout):
                await client.__aexit__(exc_type, exc_value, traceback)
        except TimeoutError as error:
            self._state = _LifecycleState.CLOSE_FAILED
            raise AgentCommunityTransportError(
                f"Timed out while attempting to close after {self._timeout:g} seconds"
            ) from error
        except Exception as error:
            self._state = _LifecycleState.CLOSE_FAILED
            raise AgentCommunityTransportError(
                "Failed to close the Agent Community MCP connection"
            ) from error
        else:
            self._client = None
            self._owner_task_id = None
            self._state = _LifecycleState.CLOSED
        finally:
            if self._state is _LifecycleState.CLOSING:
                self._state = _LifecycleState.CLOSE_FAILED

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> CallToolResult:
        if self._state is _LifecycleState.CONNECTING:
            raise AgentCommunityProtocolError(
                "Cannot call tools while client is connecting"
            )
        if self._state is _LifecycleState.CALLING:
            raise AgentCommunityProtocolError("Concurrent tool calls are not supported")
        if self._state is _LifecycleState.CLOSING:
            raise AgentCommunityProtocolError(
                "Cannot call tools while client is closing"
            )
        if self._state is _LifecycleState.CLOSE_FAILED:
            raise AgentCommunityProtocolError(
                "Cannot call tools after a failed close; retry close first"
            )
        if self._state is not _LifecycleState.OPEN:
            raise AgentCommunityProtocolError(
                "Tool calls require an active context for this client"
            )

        client = self._client
        if client is None:
            raise AgentCommunityProtocolError("Client lifecycle state is inconsistent")
        self._state = _LifecycleState.CALLING

        try:
            with fail_after(self._timeout):
                return await client.call_tool(name, arguments)
        except TimeoutError as error:
            raise AgentCommunityTransportError(
                f"Tool {name!r} timed out after {self._timeout:g} seconds"
            ) from error
        except ValidationError as error:
            raise AgentCommunityProtocolError(
                f"MCP tool {name!r} returned a protocol-invalid result"
            ) from error
        except Exception as error:
            raise AgentCommunityTransportError(
                f"Failed while calling MCP tool {name!r}"
            ) from error
        finally:
            if self._state is _LifecycleState.CALLING:
                self._state = _LifecycleState.OPEN
