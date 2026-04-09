import json
import logging
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)


class MCPWeatherClient:
    """Manages a persistent connection to mcp_weather_server via stdio."""

    def __init__(self):
        self._session: ClientSession | None = None
        self._tools: list[dict] = []
        self._exit_stack = None

    async def connect(self) -> None:
        """Start the weather server subprocess and initialise the MCP session."""
        from contextlib import AsyncExitStack

        server_params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "mcp_weather_server", "--mode", "stdio"],
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
        logger.debug("[MCP] list_tools response: %s", [
            {"name": t.name, "description": t.description, "inputSchema": t.inputSchema}
            for t in result.tools
        ])
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
            raise RuntimeError("MCPWeatherClient is not connected")
        logger.debug("[MCP] call_tool → name=%s arguments=%s", name, arguments)
        result = await self._session.call_tool(name, arguments=arguments)
        logger.debug(
            "[MCP] call_tool ← name=%s isError=%s content=%s",
            name,
            getattr(result, "isError", None),
            [
                item.text if hasattr(item, "text") else str(item)
                for item in result.content
            ],
        )
        parts = []
        for item in result.content:
            if hasattr(item, "text"):
                parts.append(item.text)
            else:
                parts.append(str(item))
        return "\n".join(parts)