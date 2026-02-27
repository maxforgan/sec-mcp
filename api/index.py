import asyncio
import json
import sys
import os

# Add parent directory to path so we can import our modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from http.server import BaseHTTPRequestHandler

from sec_mcp import SECClient, format_filings_output
from sec_financials import SECFinancialsClient, format_financial_statement
from sec_tables import SECTableExtractor
from sec_13f import SEC13FClient, format_13f_holdings


async def dispatch(method: str, params: dict):
    if method == "list_tools":
        from server import handle_list_tools
        tools = await handle_list_tools()
        return [tool.dict() for tool in tools]

    elif method == "call_tool":
        if not params:
            raise ValueError("Missing params")
        tool_name = params.get("name")
        tool_args = params.get("arguments")
        if not tool_name:
            raise ValueError("Missing tool name")
        from server import handle_call_tool
        result = await handle_call_tool(tool_name, tool_args)
        return [res.dict() for res in result]

    else:
        raise ValueError(f"Unknown method: {method}")


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        try:
            data = json.loads(body)
            method = data.get("method")
            params = data.get("params")

            result = asyncio.run(dispatch(method, params))

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"result": result}).encode())

        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "SEC EDGAR MCP Server running"}).encode())
