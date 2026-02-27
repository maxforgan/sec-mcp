#!/usr/bin/env python3
"""
Analyst Estimates MCP Server
Exposes analyst estimates retrieval as an MCP tool for Claude Desktop.
"""

import asyncio
from typing import Any
from mcp.server.models import InitializationOptions
import mcp.types as types
from mcp.server import NotificationOptions, Server
import mcp.server.stdio

from analyst_estimates import AnalystEstimatesClient, format_estimates_output


# Create server instance
server = Server("analyst-estimates")


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """List available analyst estimates tools."""
    return [
        types.Tool(
            name="get-analyst-estimates",
            description=(
                "Retrieve comprehensive analyst estimates and consensus data for a stock. "
                "Includes earnings (EPS) estimates, revenue estimates, growth projections, "
                "EPS trends and revisions, earnings history (actual vs estimate), "
                "analyst recommendations, and price targets. "
                "Data covers quarterly and annual periods with consensus ranges (high/low/average)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "Stock ticker symbol (e.g., AAPL, MSFT, TSLA, GOOGL)",
                    },
                },
                "required": ["ticker"],
            },
        ),
    ]


@server.call_tool()
async def handle_call_tool(
    name: str, arguments: dict | None
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Handle tool execution requests."""

    if name != "get-analyst-estimates":
        raise ValueError(f"Unknown tool: {name}")

    if not arguments:
        raise ValueError("Missing arguments")

    ticker = arguments.get("ticker")
    if not ticker:
        raise ValueError("Missing required argument: ticker")

    try:
        # Create client and fetch estimates
        client = AnalystEstimatesClient()
        estimates = client.get_estimates(ticker)

        # Format the output
        output = format_estimates_output(estimates)

        return [
            types.TextContent(
                type="text",
                text=output
            )
        ]

    except Exception as e:
        return [
            types.TextContent(
                type="text",
                text=f"Error retrieving analyst estimates: {str(e)}"
            )
        ]


async def main():
    """Run the MCP server using stdio transport."""
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="analyst-estimates",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())