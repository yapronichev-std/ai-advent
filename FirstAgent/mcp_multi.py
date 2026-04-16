"""Composite MCP client that aggregates tools from multiple underlying clients."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class MultiMCPClient:
    """
    Wraps several MCP clients and presents a unified tools / call_tool interface.

    Each sub-client is connected / disconnected independently; failures in one
    client are logged as warnings but do not prevent the others from loading.
    """

    def __init__(self, clients: list) -> None:
        self._clients = clients
        self._tool_map: dict[str, Any] = {}  # tool_name → owning client

    async def connect(self) -> None:
        """Connect all sub-clients and build the tool dispatch map."""
        for client in self._clients:
            try:
                await client.connect()
                logger.info(
                    "[MultiMCP] %s connected — tools: %s",
                    client.__class__.__name__,
                    [t["function"]["name"] for t in client.tools],
                )
            except Exception as exc:
                logger.warning(
                    "[MultiMCP] %s failed to connect: %s",
                    client.__class__.__name__,
                    exc,
                )
        self._build_tool_map()

    async def disconnect(self) -> None:
        """Disconnect all sub-clients."""
        for client in self._clients:
            try:
                await client.disconnect()
            except Exception as exc:
                logger.warning(
                    "[MultiMCP] error disconnecting %s: %s",
                    client.__class__.__name__,
                    exc,
                )

    def _build_tool_map(self) -> None:
        self._tool_map = {}
        for client in self._clients:
            for tool in client.tools:
                name = tool["function"]["name"]
                self._tool_map[name] = client

    @property
    def tools(self) -> list[dict]:
        result: list[dict] = []
        for client in self._clients:
            result.extend(client.tools)
        return result

    async def call_tool(self, name: str, arguments: dict) -> str:
        """Dispatch a tool call to the client that owns that tool."""
        client = self._tool_map.get(name)
        if client is None:
            raise ValueError(f"No MCP client handles tool '{name}'")
        return await client.call_tool(name, arguments)