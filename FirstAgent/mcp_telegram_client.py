"""MCP-клиент для подключения к telegram_mcp_server через stdio."""

import logging
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)

_SERVER_SCRIPT = str(Path(__file__).parent / "mcp_telegram_server" / "server.py")


class MCPTelegramClient:
    """Управляет соединением с telegram_mcp_server через stdio."""

    def __init__(self) -> None:
        self._session: ClientSession | None = None
        self._tools: list[dict] = []
        self._exit_stack = None

    async def connect(self) -> None:
        from contextlib import AsyncExitStack

        server_params = StdioServerParameters(
            command=sys.executable,
            args=[_SERVER_SCRIPT],
        )

        self._exit_stack = AsyncExitStack()
        read, write = await self._exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        self._session = await self._exit_stack.enter_async_context(
            ClientSession(read, write)
        )
        await self._session.initialize()
        await self._refresh_tools()

    async def disconnect(self) -> None:
        if self._exit_stack:
            await self._exit_stack.aclose()
            self._exit_stack = None
            self._session = None
            self._tools = []

    async def _refresh_tools(self) -> None:
        result = await self._session.list_tools()
        logger.debug("[MCP telegram] list_tools: %s", [t.name for t in result.tools])
        self._tools = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description or "",
                    "parameters": t.inputSchema,
                },
            }
            for t in result.tools
        ]

    @property
    def tools(self) -> list[dict]:
        return self._tools

    async def call_tool(self, name: str, arguments: dict) -> str:
        if not self._session:
            raise RuntimeError("MCPTelegramClient is not connected")
        logger.debug("[MCP telegram] call_tool → %s  args=%s", name, list(arguments.keys()))
        result = await self._session.call_tool(name, arguments=arguments)
        parts = [
            item.text if hasattr(item, "text") else str(item)
            for item in result.content
        ]
        return "\n".join(parts)