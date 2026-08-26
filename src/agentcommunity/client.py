from __future__ import annotations

import math
from types import TracebackType
from typing import Any, TypeVar
from unicodedata import category
from urllib.parse import urlsplit

from mcp.types import TextContent
from pydantic import BaseModel, ValidationError

from agentcommunity._transport import _ClientFactory, _MCPTransport
from agentcommunity.errors import AgentCommunityProtocolError, AgentCommunityToolError

_DEFAULT_ENDPOINT = "https://agentcommunity.org/mcp"
_DEFAULT_TIMEOUT = 15.0
_MAX_TOOL_ERROR_TEXT = 500
_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")
_UNSAFE_UNICODE_CATEGORIES = frozenset({"Cc", "Cf", "Cs"})

_ModelT = TypeVar("_ModelT", bound=BaseModel)


class AgentCommunityClient:
    def __init__(
        self,
        endpoint: str = _DEFAULT_ENDPOINT,
        timeout: float = _DEFAULT_TIMEOUT,
        *,
        _client_factory: _ClientFactory | None = None,
    ) -> None:
        self._endpoint = _validate_endpoint(endpoint)
        self._timeout = _validate_timeout(timeout)
        self._transport = _MCPTransport(
            self._endpoint,
            self._timeout,
            client_factory=_client_factory,
        )

    @property
    def endpoint(self) -> str:
        return self._endpoint

    @property
    def timeout(self) -> float:
        return self._timeout

    async def __aenter__(self) -> AgentCommunityClient:
        await self._transport.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self._transport.close(exc_type, exc_value, traceback)

    async def close(self) -> None:
        await self._transport.close()

    async def _call_typed(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        model_type: type[_ModelT],
    ) -> _ModelT:
        result = await self._transport.call_tool(tool_name, arguments)
        if result.is_error:
            diagnostic = _safe_tool_error_text(result.content)
            message = f"MCP tool {tool_name!r} reported an error"
            if diagnostic:
                message = f"{message}: {diagnostic}"
            raise AgentCommunityToolError(message)
        if result.structured_content is None:
            raise AgentCommunityProtocolError(
                f"MCP tool {tool_name!r} returned no structured content"
            )
        try:
            return model_type.model_validate(result.structured_content)
        except ValidationError as error:
            raise AgentCommunityProtocolError(
                f"MCP tool {tool_name!r} returned invalid structured content"
            ) from error


def _validate_endpoint(endpoint: str) -> str:
    if not isinstance(endpoint, str):
        raise TypeError("endpoint must be a string")
    if not endpoint or endpoint.strip() != endpoint:
        raise ValueError("endpoint must be a non-empty absolute HTTP(S) URL")
    if any(ord(character) <= 32 or ord(character) == 127 for character in endpoint):
        raise ValueError("endpoint must not contain whitespace or control characters")
    try:
        parsed = urlsplit(endpoint)
        parsed_port = parsed.port
    except ValueError as error:
        raise ValueError("endpoint is not a valid HTTP(S) URL") from error
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("endpoint must be an absolute HTTP(S) URL")
    if any(
        _has_invalid_percent_escape(component)
        for component in (parsed.netloc, parsed.path, parsed.query)
    ):
        raise ValueError("endpoint contains an invalid percent escape")
    if parsed.hostname is None or (
        parsed_port is not None and not 0 < parsed_port < 65536
    ):
        raise ValueError("endpoint must include a valid host and port")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("endpoint must not contain credentials")
    if parsed.fragment:
        raise ValueError("endpoint must not contain a fragment")
    return endpoint


def _has_invalid_percent_escape(value: str) -> bool:
    index = 0
    while index < len(value):
        if value[index] != "%":
            index += 1
            continue
        escape = value[index + 1 : index + 3]
        if len(escape) != 2 or not set(escape) <= _HEX_DIGITS:
            return True
        index += 3
    return False


def _validate_timeout(timeout: float) -> float:
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise TypeError("timeout must be an int or float")
    value = float(timeout)
    if not math.isfinite(value) or value <= 0:
        raise ValueError("timeout must be positive and finite")
    return value


def _safe_tool_error_text(content: list[Any]) -> str:
    output: list[str] = []
    pending_space = False
    truncated = False
    for item in content:
        if not isinstance(item, TextContent):
            continue
        if output:
            pending_space = True
        for character in item.text:
            if character.isspace() or category(character) in _UNSAFE_UNICODE_CATEGORIES:
                if output:
                    pending_space = True
                continue
            if pending_space:
                if len(output) == _MAX_TOOL_ERROR_TEXT:
                    truncated = True
                    break
                output.append(" ")
                pending_space = False
            if len(output) == _MAX_TOOL_ERROR_TEXT:
                truncated = True
                break
            output.append(character)
            if len(output) == _MAX_TOOL_ERROR_TEXT:
                truncated = True
                break
        if truncated:
            break
    diagnostic = "".join(output)
    if truncated:
        return f"{diagnostic[: _MAX_TOOL_ERROR_TEXT - 3]}..."
    return diagnostic
