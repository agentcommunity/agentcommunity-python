from __future__ import annotations

import math
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from enum import Enum, auto
from types import TracebackType
from typing import Any, Protocol, cast

from anyio import fail_after, get_current_task
from jsonschema.exceptions import (  # type: ignore[import-untyped]
    ValidationError as JsonSchemaValidationError,
)
from mcp import Client, MCPError
from mcp.types import REQUEST_TIMEOUT, CallToolResult
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
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        read_timeout_seconds: float | None = None,
    ) -> CallToolResult: ...


_ClientFactory = Callable[[str, float], _HighLevelClient]


class _LifecycleState(Enum):
    NEW = auto()
    CONNECTING = auto()
    OPEN = auto()
    CALLING = auto()
    CLOSING = auto()
    CLOSE_FAILED = auto()
    CLOSED = auto()


def _create_mcp_client(endpoint: str, timeout: float) -> _HighLevelClient:
    return cast(_HighLevelClient, Client(endpoint, read_timeout_seconds=timeout))


@asynccontextmanager
async def _client_lifecycle(
    endpoint: str,
    timeout: float,
    client_factory: _ClientFactory,
) -> AsyncIterator[_HighLevelClient]:
    client = client_factory(endpoint, timeout)
    # This scope must outlive every scope opened by the official client. Exiting a
    # shorter wrapper around either lifecycle method violates AnyIO's scope LIFO.
    with fail_after(timeout) as connection_scope:
        async with client as connected:
            connection_scope.deadline = math.inf
            yield connected


def _is_output_schema_failure(error: RuntimeError) -> bool:
    return isinstance(error.__cause__, JsonSchemaValidationError)


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
        self._lifecycle: AbstractAsyncContextManager[_HighLevelClient] | None = None
        self._state = _LifecycleState.NEW
        self._owner_task_id: int | None = None

    @property
    def active(self) -> bool:
        return self._state in {
            _LifecycleState.CONNECTING,
            _LifecycleState.OPEN,
            _LifecycleState.CALLING,
            _LifecycleState.CLOSING,
        }

    async def connect(self) -> None:
        if self._state is _LifecycleState.CONNECTING:
            raise AgentCommunityProtocolError("Client is already connecting")
        if self._state is _LifecycleState.CLOSING:
            raise AgentCommunityProtocolError("Client is currently closing")
        if self._state is _LifecycleState.CLOSE_FAILED:
            raise AgentCommunityProtocolError(
                "Client teardown failed and this instance cannot be reused"
            )
        if self._state in {_LifecycleState.OPEN, _LifecycleState.CALLING}:
            raise AgentCommunityProtocolError("Client context is already active")

        previous_state = self._state
        self._state = _LifecycleState.CONNECTING
        self._owner_task_id = get_current_task().id
        lifecycle = _client_lifecycle(
            self._endpoint, self._timeout, self._client_factory
        )
        self._lifecycle = lifecycle
        try:
            client = await lifecycle.__aenter__()
        except TimeoutError as error:
            raise AgentCommunityTransportError(
                f"Timed out while attempting to connect after {self._timeout:g} seconds"
            ) from error
        except ValidationError as error:
            raise AgentCommunityProtocolError(
                "MCP initialization returned protocol-invalid data"
            ) from error
        except MCPError as error:
            if error.code == REQUEST_TIMEOUT:
                raise AgentCommunityTransportError(
                    "Timed out while attempting to connect "
                    f"after {self._timeout:g} seconds"
                ) from error
            raise AgentCommunityTransportError(
                "Failed to connect to the Agent Community MCP endpoint"
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
                self._lifecycle = None

    async def close(
        self,
        exc_type: type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> None:
        if self._state in {
            _LifecycleState.NEW,
            _LifecycleState.CLOSE_FAILED,
            _LifecycleState.CLOSED,
        }:
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

        lifecycle = self._lifecycle
        if lifecycle is None:
            raise AgentCommunityProtocolError("Client lifecycle state is inconsistent")
        self._state = _LifecycleState.CLOSING

        try:
            await lifecycle.__aexit__(exc_type, exc_value, traceback)
        except Exception as error:
            raise AgentCommunityTransportError(
                "Failed to close the Agent Community MCP connection"
            ) from error
        else:
            self._state = _LifecycleState.CLOSED
        finally:
            if self._state is _LifecycleState.CLOSING:
                self._state = _LifecycleState.CLOSE_FAILED
            self._client = None
            self._lifecycle = None
            self._owner_task_id = None

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
        if self._state is not _LifecycleState.OPEN:
            raise AgentCommunityProtocolError(
                "Tool calls require an active context for this client"
            )

        client = self._client
        if client is None:
            raise AgentCommunityProtocolError("Client lifecycle state is inconsistent")
        self._state = _LifecycleState.CALLING

        try:
            return await client.call_tool(
                name, arguments, read_timeout_seconds=self._timeout
            )
        except ValidationError as error:
            raise AgentCommunityProtocolError(
                f"MCP tool {name!r} returned a protocol-invalid result"
            ) from error
        except RuntimeError as error:
            if _is_output_schema_failure(error):
                raise AgentCommunityProtocolError(
                    f"MCP tool {name!r} returned a protocol-invalid result"
                ) from error
            raise AgentCommunityTransportError(
                f"Failed while calling MCP tool {name!r}"
            ) from error
        except MCPError as error:
            if error.code == REQUEST_TIMEOUT:
                raise AgentCommunityTransportError(
                    f"Tool {name!r} timed out after {self._timeout:g} seconds"
                ) from error
            raise AgentCommunityTransportError(
                f"Failed while calling MCP tool {name!r}"
            ) from error
        except TimeoutError as error:
            raise AgentCommunityTransportError(
                f"Tool {name!r} timed out after {self._timeout:g} seconds"
            ) from error
        except Exception as error:
            raise AgentCommunityTransportError(
                f"Failed while calling MCP tool {name!r}"
            ) from error
        finally:
            if self._state is _LifecycleState.CALLING:
                self._state = _LifecycleState.OPEN
