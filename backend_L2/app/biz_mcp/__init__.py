"""
biz_mcp/__init__.py — MCP management domain entry point.

Exports api_router for automatic discovery by main.py.
"""

from fastapi import APIRouter

from .server.api import router as server_router
from .tool.api import router as tool_router
from .caller.api import router as caller_router

api_router = APIRouter()

# Admin routes: /api/admin/mcp/servers and /api/admin/mcp/tools
api_router.include_router(server_router, prefix="/admin/mcp/servers", tags=["MCP Servers"])
api_router.include_router(tool_router, prefix="/admin/mcp/tools", tags=["MCP Tools"])

# Caller routes: /api/mcp/call and /api/mcp/available
api_router.include_router(caller_router, prefix="/mcp", tags=["MCP"])

__all__ = ["api_router"]
