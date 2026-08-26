from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from mcp.types import CallToolResult, TextContent


class FakeMCPClient:
    def __init__(self) -> None:
        self.enter_count = 0
        self.exit_count = 0
        self.successful_exit_count = 0
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.connect_error: BaseException | None = None
        self.close_error: BaseException | None = None
        self.call_error: BaseException | None = None
        self.connect_gate: asyncio.Event | None = None
        self.close_gate: asyncio.Event | None = None
        self.call_gate: asyncio.Event | None = None
        self.results: list[CallToolResult] = []

    async def __aenter__(self) -> FakeMCPClient:
        self.enter_count += 1
        if self.connect_gate is not None:
            await self.connect_gate.wait()
        if self.connect_error is not None:
            raise self.connect_error
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None:
        del exc_type, exc_value, traceback
        self.exit_count += 1
        if self.close_gate is not None:
            await self.close_gate.wait()
        if self.close_error is not None:
            raise self.close_error
        self.successful_exit_count += 1

    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> CallToolResult:
        self.calls.append((name, arguments or {}))
        if self.call_gate is not None:
            await self.call_gate.wait()
        if self.call_error is not None:
            raise self.call_error
        if self.results:
            return self.results.pop(0)
        return successful_result()


class RecordingClientFactory:
    def __init__(self, build: Callable[[], FakeMCPClient] = FakeMCPClient) -> None:
        self._build = build
        self.endpoints: list[str] = []
        self.clients: list[FakeMCPClient] = []

    def __call__(self, endpoint: str) -> FakeMCPClient:
        self.endpoints.append(endpoint)
        client = self._build()
        self.clients.append(client)
        return client


def successful_result(structured_content: Any | None = None) -> CallToolResult:
    if structured_content is None:
        structured_content = {"member_count": 29_700, "note": "Verified members"}
    return CallToolResult(content=[], structured_content=structured_content)


def error_result(text: str) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(text=text)],
        is_error=True,
    )
