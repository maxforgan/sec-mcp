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


app = Starlette(routes=[
    Route("/api/mcp", endpoint=handle_sse),
    Mount("/api/mcp/message", app=sse.handle_post_message),
])
