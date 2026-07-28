"""
biz_mcp/caller/service.py — MCP Tool caller.
Handles invoking external MCP Server endpoints.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional
from uuid import UUID

import httpx

from ..server import repository as server_repo

from ..registry import MCPRegistry

log = logging.getLogger(__name__)


class MCPToolCallError(Exception):
    """Raised when a tool call fails."""
    pass


class MCPServerDisabledError(Exception):
    pass


class MCPToolDisabledError(Exception):
    pass


def _get_mcp_base_url() -> str:
    """Get the MCP Server base URL from config or environment."""
    import os
    return os.environ.get(
        "MCP_SERVER_BASE_URL",
        "http://localhost:3100",
    )


async def call_tool(
    server_id: str,
    tool_name: str,
    arguments: Dict[str, Any],
    tenant_id: str,
) -> Dict[str, Any]:
    """
    Call an MCP tool via the configured MCP Server.

    1. Fetch server config from DB
    2. Fetch tool schema from DB
    3. POST to MCP Server /tools/call
    4. Return parsed result
    """
    # Load server
    server = server_repo.get_by_id(server_id)
    if server is None:
        raise ValueError(f"Server {server_id} not found")
    if str(server["tenant_id"]) != tenant_id:
        raise ValueError(f"Server {server_id} not found")
    if not server["is_enabled"]:
        raise MCPServerDisabledError("MCP Server is disabled")

    # Load tool
    tools = server_repo.list_tools_by_server(server_id)
    tool_row = next((t for t in tools if t["tool_name"] == tool_name), None)
    if tool_row is None:
        raise ValueError(f"Tool '{tool_name}' not found in server")
    if not tool_row["is_enabled"]:
        raise MCPToolDisabledError(f"Tool '{tool_name}' is disabled")

    # Get MCP Server endpoint
    config = server.get("config_json") or {}
    base_url = config.get("base_url") or _get_mcp_base_url()
    # Strip trailing slash
    base_url = base_url.rstrip("/")

    # Build the call payload
    payload = {
        "name": tool_name,
        "arguments": arguments,
    }

    start_ms = time.time()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{base_url}/tools/call",
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            elapsed_ms = int((time.time() - start_ms) * 1000)

            if not response.is_success:
                log.warning(
                    "[MCP] Tool call failed: server=%s tool=%s status=%s body=%s",
                    server_id, tool_name, response.status_code, response.text[:500],
                )
                raise MCPToolCallError(
                    f"MCP Server returned {response.status_code}: {response.text[:200]}"
                )

            result = response.json()
            log.info(
                "[MCP] Tool call success: server=%s tool=%s latency=%dms",
                server_id, tool_name, elapsed_ms,
            )
            return {
                "success": True,
                "result": result,
                "latency_ms": elapsed_ms,
            }

    except httpx.TimeoutException:
        elapsed_ms = int((time.time() - start_ms) * 1000)
        log.warning("[MCP] Tool call timeout: server=%s tool=%s", server_id, tool_name)
        raise MCPToolCallError("MCP Server request timed out after 30s")
    except Exception as e:
        elapsed_ms = int((time.time() - start_ms) * 1000)
        log.exception("[MCP] Tool call error: server=%s tool=%s", server_id, tool_name)
        raise MCPToolCallError(f"Failed to call MCP tool: {e}")
