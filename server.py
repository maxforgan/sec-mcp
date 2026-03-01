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
from sec_13f import SEC13FClient, format_13f_holdings, format_13f_history
from sec_8k import SEC8KClient, format_press_releases
from sec_filing_text import SECFilingTextClient, format_filing_text
from sec_form4 import SECForm4Client, format_insider_transactions
from sec_13d_13g import SEC13D13GClient, format_ownership_disclosures
from sec_form144 import SECForm144Client, format_form144_notifications
from sec_company_search import SECCompanySearchClient, format_company_search_results


# Create server instance
server = Server("sec-edgar")


def _resolve_periods(arguments: dict, default: int = 8) -> int:
    """
    Resolve the number of periods to fetch.
    If 'years' is provided, compute periods = years * 5 to account for
    ~4 periods per year (3 quarterly + 1 annual) with a buffer.
    Otherwise fall back to the explicit 'periods' argument or the default.
    """
    years = arguments.get("years")
    if years is not None:
        return max(1, int(years) * 5)
    return int(arguments.get("periods", default))


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
                "Returns revenues, cost of revenue, gross profit, R&D, SG&A, operating expenses, operating income, "
                "interest expense, income tax, net income, and EPS. Each period is labeled as Annual (10-K) "
                "or Quarterly (10-Q), sorted most recent first.\n\n"
                "Use 'years' to request a time range (e.g., years=5 for 5 years of history). "
                "Results include both annual and quarterly filings — 1 year ≈ 4 periods (3 quarters + 1 annual)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "Stock ticker symbol (e.g., AAPL, MSFT, TSLA)",
                    },
                    "years": {
                        "type": "number",
                        "description": "Number of years of history to retrieve (e.g., 5 for five years). Overrides 'periods' when provided. 1 year ≈ 4 periods.",
                    },
                    "periods": {
                        "type": "number",
                        "description": "Number of individual periods to retrieve (default: 8). Use 'years' instead when you want a specific time range.",
                        "default": 8,
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
                "with its filing type (10-K or 10-Q).\n\n"
                "Use 'years' to request a time range (e.g., years=5 for 5 years of history)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "Stock ticker symbol (e.g., AAPL, MSFT, TSLA)",
                    },
                    "years": {
                        "type": "number",
                        "description": "Number of years of history to retrieve (e.g., 5 for five years). Overrides 'periods' when provided. 1 year ≈ 4 periods.",
                    },
                    "periods": {
                        "type": "number",
                        "description": "Number of individual periods to retrieve (default: 8). Use 'years' instead when you want a specific time range.",
                        "default": 8,
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
                "Each period is labeled as Annual (10-K) or Quarterly (10-Q).\n\n"
                "Use 'years' to request a time range (e.g., years=5 for 5 years of history)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "Stock ticker symbol (e.g., AAPL, MSFT, TSLA)",
                    },
                    "years": {
                        "type": "number",
                        "description": "Number of years of history to retrieve (e.g., 5 for five years). Overrides 'periods' when provided. 1 year ≈ 4 periods.",
                    },
                    "periods": {
                        "type": "number",
                        "description": "Number of individual periods to retrieve (default: 8). Use 'years' instead when you want a specific time range.",
                        "default": 8,
                    },
                },
                "required": ["ticker"],
            },
        ),
        types.Tool(
            name="get-formatted-income-statement",
            description=(
                "Extract the income statement in its original formatted table layout from the latest SEC filing. "
                "Supports both 10-K (annual) and 10-Q (quarterly). "
                "Returns the actual table as it appears in the filing with all line items, periods, and formatting preserved."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "Stock ticker symbol (e.g., AAPL, MSFT, TSLA)",
                    },
                    "filing_type": {
                        "type": "string",
                        "description": "Filing type: '10-K' (annual, default) or '10-Q' (most recent quarterly)",
                        "default": "10-K",
                    },
                },
                "required": ["ticker"],
            },
        ),
        types.Tool(
            name="get-formatted-balance-sheet",
            description=(
                "Extract the balance sheet in its original formatted table layout from the latest SEC filing. "
                "Supports both 10-K (annual) and 10-Q (quarterly). "
                "Returns the actual table as it appears in the filing with all line items and periods preserved."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "Stock ticker symbol (e.g., AAPL, MSFT, TSLA)",
                    },
                    "filing_type": {
                        "type": "string",
                        "description": "Filing type: '10-K' (annual, default) or '10-Q' (most recent quarterly)",
                        "default": "10-K",
                    },
                },
                "required": ["ticker"],
            },
        ),
        types.Tool(
            name="get-formatted-cash-flow",
            description=(
                "Extract the cash flow statement in its original formatted table layout from the latest SEC filing. "
                "Supports both 10-K (annual) and 10-Q (quarterly). "
                "Returns the actual table as it appears in the filing with all line items and periods preserved."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "Stock ticker symbol (e.g., AAPL, MSFT, TSLA)",
                    },
                    "filing_type": {
                        "type": "string",
                        "description": "Filing type: '10-K' (annual, default) or '10-Q' (most recent quarterly)",
                        "default": "10-K",
                    },
                },
                "required": ["ticker"],
            },
        ),
        types.Tool(
            name="get-13f-holdings",
            description=(
                "Get the latest 13F holdings for an investment firm, with optional multi-quarter history. "
                "Returns holdings sorted by value. When quarters>1, also shows new/closed positions and "
                "significant changes between the most recent and prior quarter.\n\n"
                "IMPORTANT: Investment firms don't have stock tickers — use their CIK number. "
                "Workflow: search-company(name='Firm Name') → copy CIK → get-13f-holdings(ticker_or_cik='CIK').\n\n"
                "Examples:\n"
                "  Latest holdings: ticker_or_cik='0001901865'\n"
                "  Past year (4Q):  ticker_or_cik='0001901865', quarters=4\n"
                "  Past 3 years:    ticker_or_cik='0001901865', quarters=12"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker_or_cik": {
                        "type": "string",
                        "description": "Ticker symbol or CIK of the investment firm. Use search-company to find the CIK if you only have a name (e.g., '0001901865' for Divisadero, '0001067983' for Berkshire).",
                    },
                    "quarters": {
                        "type": "number",
                        "description": (
                            "Number of quarterly 13F filings to retrieve (default: 1 = latest only). "
                            "Use 4 for 1 year, 8 for 2 years, 12 for 3 years. "
                            "When >1, output includes position changes vs prior quarter."
                        ),
                        "default": 1,
                    },
                    "top_n": {
                        "type": "number",
                        "description": "Number of top holdings to display in the current-quarter table (default: 20)",
                        "default": 20,
                    },
                    "return_all": {
                        "type": "boolean",
                        "description": "If true, show all holdings (not just top N) when quarters=1. Ignored when quarters>1.",
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
        types.Tool(
            name="get-filing-text",
            description=(
                "Retrieve the full text of a SEC filing with optional section extraction. "
                "Supports 10-K, 10-Q, DEF 14A (proxy statements), SC 13G, SC 13D, S-1, and other filing types.\n\n"
                "10-K sections: 'business', 'risk factors', 'mda', 'financial statements', 'notes'/'footnotes'.\n"
                "10-Q sections: 'financial statements', 'mda', 'risk factors', 'notes'/'footnotes'.\n"
                "DEF 14A (proxy) sections: 'executive compensation'/'comp', 'directors'/'board', "
                "'say-on-pay', 'audit', 'proposals', 'ownership', 'related party', 'pay ratio'.\n"
                "S-1 sections: 'business', 'risk factors' (same as 10-K).\n\n"
                "IMPORTANT: Notes/footnotes and proxy compensation sections are large. "
                "Use max_chars=200000 or higher for those sections."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "Stock ticker symbol (e.g., AAPL, MSFT, TSLA)",
                    },
                    "filing_type": {
                        "type": "string",
                        "description": (
                            "Filing type to retrieve. Common values: "
                            "'10-K' (annual report, default), '10-Q' (quarterly), "
                            "'DEF 14A' (proxy statement — exec comp, director elections), "
                            "'SC 13G' or 'SC 13D' (large shareholder >5% ownership filings), "
                            "'S-1' (IPO registration statement — supports 'business' and 'risk factors' sections)."
                        ),
                        "default": "10-K",
                    },
                    "section": {
                        "type": "string",
                        "description": (
                            "Named section to extract. "
                            "For DEF 14A: 'executive compensation', 'comp', 'directors', 'board', "
                            "'say-on-pay', 'audit', 'proposals', 'ownership', 'related party', 'pay ratio'. "
                            "For 10-K: 'mda', 'risk factors', 'business', 'notes', 'financial statements'. "
                            "For S-1: 'business', 'risk factors' (same as 10-K). "
                            "Omit to return the full filing (very large — always specify a section)."
                        ),
                    },
                    "count": {
                        "type": "number",
                        "description": "Number of recent filings to retrieve (default: 1)",
                        "default": 1,
                    },
                    "max_chars": {
                        "type": "number",
                        "description": (
                            "Maximum characters to return (default: 100000). "
                            "Executive compensation tables and footnotes can be 100,000–300,000 chars — use 200000+."
                        ),
                        "default": 100000,
                    },
                },
                "required": ["ticker"],
            },
        ),
        types.Tool(
            name="get-insider-transactions",
            description=(
                "Retrieve recent Form 4 insider transactions (purchases, sales, grants, option exercises) "
                "filed by directors, officers, and 10%+ shareholders of a public company.\n\n"
                "Transaction types:\n"
                "  P = Open-market Purchase (bullish signal)\n"
                "  S = Open-market Sale\n"
                "  A = Grant/Award (RSUs, options granted)\n"
                "  M = Option Exercise\n"
                "  F = Tax withholding (shares surrendered for taxes — not an open-market sale)\n\n"
                "Use transaction_types=['P','S'] to filter to only open-market buys and sells, "
                "which are the most meaningful signals of insider conviction."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "Stock ticker symbol (e.g., AAPL, MSFT, TSLA)",
                    },
                    "count": {
                        "type": "number",
                        "description": "Number of Form 4 filings to process (default: 40; each filing may have multiple transactions)",
                        "default": 40,
                    },
                    "transaction_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filter to specific transaction codes: 'P' (purchase), 'S' (sale), 'A' (grant), 'M' (exercise), 'F' (tax withholding). Omit to return all types.",
                    },
                    "show_derivatives": {
                        "type": "boolean",
                        "description": "Include derivative transactions (RSUs, options) in output (default: true). Set false to show only direct stock transactions.",
                        "default": True,
                    },
                },
                "required": ["ticker"],
            },
        ),
        types.Tool(
            name="get-ownership-disclosures",
            description=(
                "Retrieve structured SC 13D (activist) and SC 13G (passive) ownership disclosures "
                "for large shareholders (>5% stake). Returns ownership percentages, shares owned, "
                "filing dates, and owner information. SC 13D filings also include purpose of transaction.\n\n"
                "Use this to track activist investors, passive large holders, and ownership changes over time."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "Stock ticker symbol (e.g., AAPL, MSFT, TSLA)",
                    },
                    "filing_type": {
                        "type": "string",
                        "description": (
                            "Filing type: 'SC 13G' (passive holder, default) or 'SC 13D' (activist). "
                            "SC 13D indicates potential activist intent; SC 13G is passive investment."
                        ),
                        "default": "SC 13G",
                    },
                    "count": {
                        "type": "number",
                        "description": "Number of filings to retrieve (default: 20)",
                        "default": 20,
                    },
                },
                "required": ["ticker"],
            },
        ),
        types.Tool(
            name="get-form144-notifications",
            description=(
                "Retrieve Form 144 pre-sales notifications filed by insiders before selling restricted securities. "
                "Returns proposed sale information including shares, price, sale date, and insider details.\n\n"
                "Form 144 is filed when insiders plan to sell restricted or control securities. "
                "This provides early visibility into potential insider selling activity."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "Stock ticker symbol (e.g., AAPL, MSFT, TSLA)",
                    },
                    "count": {
                        "type": "number",
                        "description": "Number of Form 144 filings to process (default: 40; each filing may contain multiple proposed sales)",
                        "default": 40,
                    },
                },
                "required": ["ticker"],
            },
        ),
        types.Tool(
            name="search-company",
            description=(
                "Search SEC EDGAR for companies or filers by name. "
                "Returns matching entity names and their CIK numbers. "
                "Use this when you have a company or fund name but no ticker symbol — "
                "for example, to find a CIK for an investment firm before calling get-13f-holdings, "
                "or to find a private company's CIK before calling get-sec-filings.\n\n"
                "Examples: 'Divisadero Capital', 'Baupost Group', 'Tiger Global', 'Pershing Square'."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Company or fund name to search for (partial match supported, e.g., 'Divisadero Capital')",
                    },
                    "filing_type": {
                        "type": "string",
                        "description": (
                            "Optional: filter results to filers of a specific form type. "
                            "Use '13F-HR' to find institutional investment managers, "
                            "'10-K' to find public companies. Leave empty to return all filer types."
                        ),
                    },
                    "count": {
                        "type": "number",
                        "description": "Maximum number of results to return (default: 20)",
                        "default": 20,
                    },
                },
                "required": ["name"],
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

            if count < 1 or count > 100:
                raise ValueError("count must be between 1 and 100")

            client = SECClient()
            filings = client.get_company_filings(
                ticker=ticker,
                count=count,
                filing_type=filing_type
            )

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
                periods = _resolve_periods(arguments)
                client = SECFinancialsClient()
                statement = await asyncio.to_thread(client.get_income_statement, ticker, periods)
                output = format_financial_statement(statement)
            elif name == "get-balance-sheet":
                periods = _resolve_periods(arguments)
                client = SECFinancialsClient()
                statement = await asyncio.to_thread(client.get_balance_sheet, ticker, periods)
                output = format_financial_statement(statement)
            elif name == "get-cash-flow-statement":
                periods = _resolve_periods(arguments)
                client = SECFinancialsClient()
                statement = await asyncio.to_thread(client.get_cash_flow_statement, ticker, periods)
                output = format_financial_statement(statement)
            elif name == "get-formatted-income-statement":
                filing_type = arguments.get("filing_type", "10-K")
                extractor = SECTableExtractor()
                output = await asyncio.to_thread(extractor.get_income_statement_table, ticker, filing_type)
            elif name == "get-formatted-balance-sheet":
                filing_type = arguments.get("filing_type", "10-K")
                extractor = SECTableExtractor()
                output = await asyncio.to_thread(extractor.get_balance_sheet_table, ticker, filing_type)
            elif name == "get-formatted-cash-flow":
                filing_type = arguments.get("filing_type", "10-K")
                extractor = SECTableExtractor()
                output = await asyncio.to_thread(extractor.get_cash_flow_table, ticker, filing_type)
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

            quarters = int(arguments.get("quarters", 1))
            top_n = int(arguments.get("top_n", 20))
            return_all = arguments.get("return_all", False)

            client = SEC13FClient()
            if quarters > 1:
                filings = await asyncio.to_thread(
                    client.get_holdings_history, ticker_or_cik, quarters
                )
                output = format_13f_history(filings, top_n=top_n)
            else:
                holdings = await asyncio.to_thread(client.get_latest_13f_holdings, ticker_or_cik)
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

        elif name == "get-filing-text":
            ticker = arguments.get("ticker")
            if not ticker:
                raise ValueError("Missing required argument: ticker")
            filing_type = arguments.get("filing_type", "10-K")
            section = arguments.get("section") or None
            count = int(arguments.get("count", 1))
            max_chars = int(arguments.get("max_chars", 100000))

            client = SECFilingTextClient()
            results = await asyncio.to_thread(
                client.get_filing_text, ticker, filing_type, section, count
            )
            output = format_filing_text(results, max_chars=max_chars)

            return [
                types.TextContent(
                    type="text",
                    text=output
                )
            ]

        elif name == "get-insider-transactions":
            ticker = arguments.get("ticker")
            if not ticker:
                raise ValueError("Missing required argument: ticker")
            count = int(arguments.get("count", 40))
            transaction_types = arguments.get("transaction_types") or None
            show_derivatives = arguments.get("show_derivatives", True)

            client = SECForm4Client()
            data = await asyncio.to_thread(
                client.get_insider_transactions, ticker, count, transaction_types
            )
            output = format_insider_transactions(
                data, show_derivatives=show_derivatives, max_rows=100
            )
            return [types.TextContent(type="text", text=output)]

        elif name == "get-ownership-disclosures":
            ticker = arguments.get("ticker")
            if not ticker:
                raise ValueError("Missing required argument: ticker")
            filing_type = arguments.get("filing_type", "SC 13G")
            count = int(arguments.get("count", 20))

            client = SEC13D13GClient()
            data = await asyncio.to_thread(
                client.get_ownership_disclosures, ticker, filing_type, count
            )
            output = format_ownership_disclosures(data, max_rows=100)
            return [types.TextContent(type="text", text=output)]

        elif name == "get-form144-notifications":
            ticker = arguments.get("ticker")
            if not ticker:
                raise ValueError("Missing required argument: ticker")
            count = int(arguments.get("count", 40))

            client = SECForm144Client()
            data = await asyncio.to_thread(
                client.get_form144_notifications, ticker, count
            )
            output = format_form144_notifications(data, max_rows=100)
            return [types.TextContent(type="text", text=output)]

        elif name == "search-company":
            query = arguments.get("name")
            if not query:
                raise ValueError("Missing required argument: name")
            count = int(arguments.get("count", 20))

            client = SECCompanySearchClient()
            results = await asyncio.to_thread(
                client.search_by_name, query, count
            )
            output = format_company_search_results(results, query)

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
        import traceback
        error_msg = f"Error: {str(e)}\n\nTraceback:\n{traceback.format_exc()}"
        return [
            types.TextContent(
                type="text",
                text=error_msg
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
