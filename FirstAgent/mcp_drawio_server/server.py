"""
MCP server that generates UML diagrams as draw.io XML.

Transport: stdio (standard MCP pattern).

Available tools:
  - generate_class_diagram
  - generate_component_diagram
  - generate_use_case_diagram
"""

import asyncio
import json
import logging
import sys

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from tools import (
    handle_generate_class_diagram,
    handle_generate_component_diagram,
    handle_generate_use_case_diagram,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger(__name__)

app = Server("mcp-drawio-uml")


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    """Advertise the three UML diagram generation tools."""
    return [
        types.Tool(
            name="generate_class_diagram",
            description=(
                "Generate a UML class diagram and return it as draw.io XML. "
                "Provide classes with optional attributes, methods, and inheritance; "
                "optionally list relations between classes."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "classes": {
                        "type": "array",
                        "description": "List of class definitions.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name":       {"type": "string"},
                                "attributes": {"type": "array", "items": {"type": "string"}},
                                "methods":    {"type": "array", "items": {"type": "string"}},
                                "inherits":   {"type": "string", "description": "Parent class name (optional)."},
                                "x":          {"type": "number"},
                                "y":          {"type": "number"},
                            },
                            "required": ["name"],
                        },
                    },
                    "relations": {
                        "type": "array",
                        "description": "Relations between classes (optional).",
                        "items": {
                            "type": "object",
                            "properties": {
                                "from": {"type": "string"},
                                "to":   {"type": "string"},
                                "type": {
                                    "type": "string",
                                    "enum": [
                                        "inheritance", "association", "dependency",
                                        "realization", "aggregation", "composition",
                                    ],
                                },
                            },
                            "required": ["from", "to", "type"],
                        },
                    },
                },
                "required": ["classes"],
            },
        ),
        types.Tool(
            name="generate_component_diagram",
            description=(
                "Generate a UML component diagram and return it as draw.io XML. "
                "Provide components and optional dependency / association relations."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "components": {
                        "type": "array",
                        "description": "List of component definitions.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "x":    {"type": "number"},
                                "y":    {"type": "number"},
                            },
                            "required": ["name"],
                        },
                    },
                    "relations": {
                        "type": "array",
                        "description": "Relations between components (optional).",
                        "items": {
                            "type": "object",
                            "properties": {
                                "from":  {"type": "string"},
                                "to":    {"type": "string"},
                                "type":  {
                                    "type": "string",
                                    "enum": ["dependency", "association", "usage", "realization"],
                                },
                                "label": {"type": "string"},
                            },
                            "required": ["from", "to"],
                        },
                    },
                },
                "required": ["components"],
            },
        ),
        types.Tool(
            name="generate_use_case_diagram",
            description=(
                "Generate a UML use case diagram and return it as draw.io XML. "
                "Provide actors, use cases, and optional relations between them."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "actors": {
                        "type": "array",
                        "description": "List of actor definitions.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "x":    {"type": "number"},
                                "y":    {"type": "number"},
                            },
                            "required": ["name"],
                        },
                    },
                    "use_cases": {
                        "type": "array",
                        "description": "List of use case definitions.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "x":    {"type": "number"},
                                "y":    {"type": "number"},
                            },
                            "required": ["name"],
                        },
                    },
                    "relations": {
                        "type": "array",
                        "description": "Relations between actors and use cases (optional).",
                        "items": {
                            "type": "object",
                            "properties": {
                                "from": {"type": "string"},
                                "to":   {"type": "string"},
                                "type": {
                                    "type": "string",
                                    "enum": ["association", "include", "extend", "generalization"],
                                },
                            },
                            "required": ["from", "to"],
                        },
                    },
                },
                "required": ["actors", "use_cases"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    """Dispatch a tool call and return the result as JSON text."""
    logger.info("call_tool: %s  args=%s", name, list(arguments.keys()))

    try:
        if name == "generate_class_diagram":
            result = handle_generate_class_diagram(arguments)
        elif name == "generate_component_diagram":
            result = handle_generate_component_diagram(arguments)
        elif name == "generate_use_case_diagram":
            result = handle_generate_use_case_diagram(arguments)
        else:
            raise ValueError(f"Unknown tool: '{name}'")

        return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]

    except Exception as exc:
        logger.exception("Error in tool '%s': %s", name, exc)
        return [types.TextContent(type="text", text=json.dumps({"error": str(exc)}))]


async def main() -> None:
    """Entry point: run the MCP server over stdio."""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())