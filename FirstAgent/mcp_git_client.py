"""MCP client that connects to the local mcp_git_server via stdio.

Supports dynamic project switching: pass project_root to connect()
to point the git tools at a different directory.
"""

import logging
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)

# Absolute path to the server entry point (runs in the same Python environment)
_SERVER_SCRIPT = str(Path(__file__).parent / "mcp_git_server" / "server.py")


class MCPGitClient:
    """Manages a persistent connection to mcp_git_server via stdio.

    The project_root parameter controls which directory the git tools
    operate on. Call disconnect() + connect(new_root) to switch projects.
    """

    def __init__(self, project_root: str | None = None) -> None:
        self.project_root: str = project_root or os.getenv("PROJECT_ROOT", str(Path.cwd()))
        self._session: ClientSession | None = None
        self._tools: list[dict] = []
        self._exit_stack = None

    async def connect(self, project_root: str | None = None) -> None:
        """Start the git server subprocess and initialise the MCP session.

        If project_root is given, it overrides the one set in __init__.
        """
        from contextlib import AsyncExitStack

        if project_root is not None:
            self.project_root = project_root

        server_params = StdioServerParameters(
            command=sys.executable,
            args=[_SERVER_SCRIPT],
            env={"PROJECT_ROOT": str(self.project_root)},
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
        logger.info(
            "[MCP git] connected — project_root=%s  tools=%d",
            self.project_root, len(self._tools),
        )

    async def disconnect(self) -> None:
        if self._exit_stack:
            await self._exit_stack.aclose()
            self._exit_stack = None
            self._session = None
            self._tools = []

    async def _refresh_tools(self) -> None:
        result = await self._session.list_tools()
        logger.debug(
            "[MCP git] list_tools: %s",
            [t.name for t in result.tools],
        )
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
            raise RuntimeError("MCPGitClient is not connected")
        logger.debug("[MCP git] call_tool → %s  args=%s", name, list(arguments.keys()))
        result = await self._session.call_tool(name, arguments=arguments)
        parts = [
            item.text if hasattr(item, "text") else str(item)
            for item in result.content
        ]
        return "\n".join(parts)
