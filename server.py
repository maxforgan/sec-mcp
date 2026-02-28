#!/usr/bin/env python3
"""
SEC EDGAR MCP Server
Exposes SEC filing retrieval as an MCP tool for Claude Desktop.
"""

import asyncio
import json
from typing import Any
from mcp.server.models import InitializationOptions
import mcp.types as types
from mcp.server import NotificationOptions, Server
from aiohttp import web

from sec_mcp import SECClient, format_filings_output
from sec_financials import SECFinancialsClient, format_financial_statement
from sec_tables import SECTableExtractor
from sec_13f import SEC13FClient, format_13f_holdings
from sec_8k import SEC8KClient, format_press_releases


# Create server instance
server = Server("sec-edgar")


async def handle_request(request: web.Request) -> web.Response:
    """Handle incoming JSON-RPC requests."""
    try:
        data = await request.json()
        method = data.get("method")
        params = data.get("params")

        if method == "list_tools":
            tools = await handle_list_tools()
            return web.json_response({"result": [tool.dict() for tool in tools]})

        elif method == "call_tool":
            if not params:
                raise ValueError("Missing params")

            tool_name = params.get("name")
            tool_args = params.get("arguments")

            if not tool_name:
                raise ValueError("Missing tool name")

            result = await handle_call_tool(tool_name, tool_args)
            return web.json_response({"result": [res.dict() for res in result]})

        else:
            return web.json_response({"error": "Unknown method"}, status=400)

    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """List available SEC EDGAR tools."""
    return [
        types.Tool(
            name="get-sec-filings",
            description=(
                "Retrieve SEC filings from EDGAR database for a given company ticker symbol. "
                "Returns recent filings including 10-K (annual), 10-Q (quarterly), 8-K (current events), and other SEC forms. "
                "Each filing includes the filing type, date, description, and a URL to view the full documents."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "Stock ticker symbol (e.g., AAPL, MSFT, TSLA, GOOGL)",
                    },
                    "count": {
                        "type": "number",
                        "description": "Number of filings to retrieve (default: 10, max: 100)",
                        "default": 10,
                    },
                    "filing_type": {
                        "type": "string",
                        "description": "Optional filter by filing type (e.g., '10-K' for annual reports, '10-Q' for quarterly, '8-K' for current events)",
                    },
                },
                "required": ["ticker"],
            },
        ),
        types.Tool(
            name="get-income-statement",
            description=(
                "Extract income statement data from SEC filings (10-K and 10-Q). "
                "Returns revenues, cost of revenue, gross profit, operating expenses, operating income, "
                "interest expense, income tax, net income, and EPS. Each period is labeled as Annual (10-K) "
                "or Quarterly (10-Q). Use periods=8 to get ~2 years of quarterly data."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "Stock ticker symbol (e.g., AAPL, MSFT, TSLA)",
                    },
                    "periods": {
                        "type": "number",
                        "description": "Number of periods to retrieve (default: 4). Includes both annual and quarterly periods sorted most recent first.",
                        "default": 4,
                    },
                },
                "required": ["ticker"],
            },
        ),
        types.Tool(
            name="get-balance-sheet",
            description=(
                "Extract balance sheet data from SEC filings (10-K and 10-Q). "
                "Returns total assets, current assets, cash, total liabilities, current liabilities, "
                "shareholders equity, long-term debt, and retained earnings. Each period is labeled "
                "with its filing type (10-K or 10-Q)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "Stock ticker symbol (e.g., AAPL, MSFT, TSLA)",
                    },
                    "periods": {
                        "type": "number",
                        "description": "Number of periods to retrieve (default: 4). Includes both annual and quarterly periods sorted most recent first.",
                        "default": 4,
                    },
                },
                "required": ["ticker"],
            },
        ),
        types.Tool(
            name="get-cash-flow-statement",
            description=(
                "Extract cash flow statement data from SEC filings (10-K and 10-Q). "
                "Returns operating cash flow, investing cash flow, financing cash flow, "
                "depreciation & amortization, capital expenditures, and dividends paid. "
                "Each period is labeled as Annual (10-K) or Quarterly (10-Q)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "Stock ticker symbol (e.g., AAPL, MSFT, TSLA)",
                    },
                    "periods": {
                        "type": "number",
                        "description": "Number of periods to retrieve (default: 4). Includes both annual and quarterly periods sorted most recent first.",
                        "default": 4,
                    },
                },
                "required": ["ticker"],
            },
        ),
        types.Tool(
            name="get-formatted-income-statement",
            description=(
                "Extract the income statement in its original formatted table layout from the latest 10-K filing. "
                "Returns the actual table as it appears in the SEC filing with all line items, periods, and formatting preserved."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "Stock ticker symbol (e.g., AAPL, MSFT, TSLA)",
                    },
                },
                "required": ["ticker"],
            },
        ),
        types.Tool(
            name="get-formatted-balance-sheet",
            description=(
                "Extract the balance sheet in its original formatted table layout from the latest 10-K filing. "
                "Returns the actual table as it appears in the SEC filing with all line items and periods preserved."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "Stock ticker symbol (e.g., AAPL, MSFT, TSLA)",
                    },
                },
                "required": ["ticker"],
            },
        ),
        types.Tool(
            name="get-formatted-cash-flow",
            description=(
                "Extract the cash flow statement in its original formatted table layout from the latest 10-K filing. "
                "Returns the actual table as it appears in the SEC filing with all line items and periods preserved."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "Stock ticker symbol (e.g., AAPL, MSFT, TSLA)",
                    },
                },
                "required": ["ticker"],
            },
        ),
        types.Tool(
            name="get-13f-holdings",
            description=(
                "Get the latest 13F holdings for an investment firm. "
                "Returns the top N holdings by value from the most recent 13F filing."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker_or_cik": {
                        "type": "string",
                        "description": "Ticker symbol or CIK of the investment firm (e.g., 'BRK-A', '0001067983')",
                    },
                    "top_n": {
                        "type": "number",
                        "description": "Number of top holdings to display (default: 20)",
                        "default": 20,
                    },
                    "return_all": {
                        "type": "boolean",
                        "description": "If true, return all holdings instead of just the top N (default: false)",
                        "default": False,
                    },
                },
                "required": ["ticker_or_cik"],
            },
        ),
        types.Tool(
            name="get-8k-press-releases",
            description=(
                "Retrieve 8-K press releases from SEC EDGAR, including the full text of "
                "Exhibit 99.1. Useful for earnings results, guidance, management commentary, "
                "and KPIs that companies choose to disclose in press releases. Note: granular "
                "operational metrics (e.g. unit volumes, resupply counts) are often only "
                "disclosed on earnings calls or in supplemental filings, not in EX-99.1."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "Stock ticker symbol (e.g., AHCO, AAPL, MSFT)",
                    },
                    "count": {
                        "type": "number",
                        "description": "Number of 8-K filings to retrieve (default: 5, max: 20)",
                        "default": 5,
                    },
                    "item_filter": {
                        "type": "string",
                        "description": (
                            "Optional: filter by 8-K item number. "
                            "Common values: '2.02' (results of operations / earnings), "
                            "'7.01' (Regulation FD disclosure), '8.01' (other events). "
                            "Leave blank to return all 8-Ks."
                        ),
                    },
                    "max_chars_per_release": {
                        "type": "number",
                        "description": (
                            "Maximum characters to return per press release (default: 50000). "
                            "Earnings releases are typically 20,000–60,000 chars. "
                            "Set higher to ensure full text is returned."
                        ),
                        "default": 50000,
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

    if not arguments:
        raise ValueError("Missing arguments")

    try:
        if name == "get-sec-filings":
            ticker = arguments.get("ticker")
            if not ticker:
                raise ValueError("Missing required argument: ticker")
            count = int(arguments.get("count", 10))
            filing_type = arguments.get("filing_type")

            # Validate count
            if count < 1 or count > 100:
                raise ValueError("count must be between 1 and 100")

            # Create SEC client and fetch filings
            client = SECClient()
            filings = client.get_company_filings(
                ticker=ticker,
                count=count,
                filing_type=filing_type
            )

            # Format the output
            output = format_filings_output(filings)

            return [
                types.TextContent(
                    type="text",
                    text=output
                )
            ]

        elif name in ["get-income-statement", "get-balance-sheet", "get-cash-flow-statement", "get-formatted-income-statement", "get-formatted-balance-sheet", "get-formatted-cash-flow"]:
            ticker = arguments.get("ticker")
            if not ticker:
                raise ValueError("Missing required argument: ticker")
            
            if name == "get-income-statement":
                periods = int(arguments.get("periods", 4))
                client = SECFinancialsClient()
                statement = client.get_income_statement(ticker, periods)
                output = format_financial_statement(statement)
            elif name == "get-balance-sheet":
                periods = int(arguments.get("periods", 4))
                client = SECFinancialsClient()
                statement = client.get_balance_sheet(ticker, periods)
                output = format_financial_statement(statement)
            elif name == "get-cash-flow-statement":
                periods = int(arguments.get("periods", 4))
                client = SECFinancialsClient()
                statement = client.get_cash_flow_statement(ticker, periods)
                output = format_financial_statement(statement)
            elif name == "get-formatted-income-statement":
                extractor = SECTableExtractor()
                output = extractor.get_income_statement_table(ticker)
            elif name == "get-formatted-balance-sheet":
                extractor = SECTableExtractor()
                output = extractor.get_balance_sheet_table(ticker)
            elif name == "get-formatted-cash-flow":
                extractor = SECTableExtractor()
                output = extractor.get_cash_flow_table(ticker)
            else:
                 raise ValueError(f"Unknown tool: {name}")

            return [
                types.TextContent(
                    type="text",
                    text=output
                )
            ]

        elif name == "get-13f-holdings":
            ticker_or_cik = arguments.get("ticker_or_cik")
            if not ticker_or_cik:
                raise ValueError("Missing required argument: ticker_or_cik")

            top_n = int(arguments.get("top_n", 20))
            return_all = arguments.get("return_all", False)

            client = SEC13FClient()
            holdings = client.get_latest_13f_holdings(ticker_or_cik)
            output = format_13f_holdings(holdings, top_n=top_n, return_all=return_all)

            return [
                types.TextContent(
                    type="text",
                    text=output
                )
            ]

        elif name == "get-8k-press-releases":
            ticker = arguments.get("ticker")
            if not ticker:
                raise ValueError("Missing required argument: ticker")
            count = min(int(arguments.get("count", 5)), 20)
            item_filter = arguments.get("item_filter") or None

            max_chars = int(arguments.get("max_chars_per_release", 50000))

            client = SEC8KClient()
            releases = await asyncio.to_thread(
                client.get_press_releases, ticker, count=count, item_filter=item_filter
            )
            output = format_press_releases(releases, max_chars_per_release=max_chars)

            return [
                types.TextContent(
                    type="text",
                    text=output
                )
            ]

        else:
            raise ValueError(f"Unknown tool: {name}")

    except ValueError as e:
        return [
            types.TextContent(
                type="text",
                text=f"Error: {str(e)}"
            )
        ]
    except Exception as e:
        return [
            types.TextContent(
                type="text",
                text=f"Error: {str(e)}"
            )
        ]


async def main():
    """Run the MCP server as an HTTP server."""
    app = web.Application()
    app.router.add_post("/", handle_request)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    print("======== Running on http://0.0.0.0:8080 ========")
    await site.start()

    # wait for cancellation
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())