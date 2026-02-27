import sys
import os

# Add parent directory to path so we can import our modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp.server.sse import SseServerTransport
from mcp.server.models import InitializationOptions
from mcp.server import NotificationOptions
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.requests import Request
from starlette.responses import JSONResponse

from server import server

sse = SseServerTransport("/api/mcp/message")


async def handle_sse(request: Request):
    async with sse.connect_sse(
        request.scope, request.receive, request._send
    ) as streams:
        await server.run(
            streams[0],
            streams[1],
            InitializationOptions(
                server_name="sec-edgar",
                server_version="1.0.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={}
                )
            )
        )


async def health(request: Request):
    return JSONResponse({"status": "SEC EDGAR MCP Server running", "endpoint": "/api/mcp"})


async def oauth_metadata(request: Request):
    return JSONResponse({
        "scopes": ["mcp"],
        "links": {
            "mcp": "/api/mcp"
        }
    })


app = Starlette(routes=[
    Route("/", endpoint=health),
    Route("/.well-known/oauth-protected-resource", endpoint=oauth_metadata),
    Route("/api/mcp", endpoint=handle_sse),
    Mount("/api/mcp/message", app=sse.handle_post_message),
])
