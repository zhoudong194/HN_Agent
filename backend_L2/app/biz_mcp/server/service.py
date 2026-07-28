"""
biz_mcp/server/service.py — Business logic for MCP Server management.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ..registry import MCPRegistry

from . import repository as repo

log = logging.getLogger(__name__)


class MCPServerNotFoundError(Exception):
    pass


class MCPServerIdentifierExistsError(Exception):
    pass


class MCPServerNotRegisteredError(Exception):
    pass


def list_servers(tenant_id: str) -> List[Dict[str, Any]]:
    return repo.list_by_tenant(tenant_id)


def get_server(server_id: str, tenant_id: str) -> Dict[str, Any]:
    server = repo.get_by_id(server_id)
    if server is None:
        raise MCPServerNotFoundError("MCP Server not found")
    if str(server["tenant_id"]) != tenant_id:
        raise MCPServerNotFoundError("MCP Server not found")
    return server


def create_server(
    tenant_id: str,
    name: str,
    identifier: str,
    description: str,
    config_json: Dict[str, Any],
    created_by: str,
) -> Dict[str, Any]:
    # Verify the identifier is registered in the registry
    server_def = MCPRegistry.get(identifier)
    if server_def is None:
        raise MCPServerNotRegisteredError(
            f"MCP Server '{identifier}' is not registered. "
            "Please register it first in the MCP registry."
        )

    # Check for duplicate identifier in this tenant
    existing = repo.list_by_tenant(tenant_id)
    if any(s["identifier"] == identifier for s in existing):
        raise MCPServerIdentifierExistsError(
            f"MCP Server '{identifier}' is already registered in this tenant."
        )

    # Create the server record
    server = repo.create(
        tenant_id=tenant_id,
        name=name,
        identifier=identifier,
        description=description,
        config_json=config_json,
        created_by=created_by,
    )

    # Sync tools from registry definition
    tools = [
        {
            "tool_name": t.name,
            "description": t.description,
            "input_schema": t.input_schema,
        }
        for t in server_def.tools
    ]
    repo.upsert_tools(str(server["id"]), tools)

    log.info(
        "[MCP] Created server '%s' (identifier=%s) for tenant %s with %d tools",
        name, identifier, tenant_id, len(tools),
    )
    return repo.get_by_id(str(server["id"]))


def update_server(
    server_id: str,
    tenant_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    config_json: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    # Verify ownership
    get_server(server_id, tenant_id)
    updated = repo.update(
        server_id=server_id,
        name=name,
        description=description,
        config_json=config_json,
    )
    return updated


def enable_server(server_id: str, tenant_id: str) -> Dict[str, Any]:
    get_server(server_id, tenant_id)
    repo.set_enabled(server_id, True)
    return repo.get_by_id(server_id)


def disable_server(server_id: str, tenant_id: str) -> Dict[str, Any]:
    get_server(server_id, tenant_id)
    repo.set_enabled(server_id, False)
    return repo.get_by_id(server_id)


def delete_server(server_id: str, tenant_id: str) -> None:
    get_server(server_id, tenant_id)
    repo.delete(server_id)
    log.info("[MCP] Deleted server %s", server_id)


def list_server_tools(server_id: str, tenant_id: str) -> List[Dict[str, Any]]:
    get_server(server_id, tenant_id)
    return repo.list_tools_by_server(server_id)


def set_tool_enabled(
    tool_id: str,
    enabled: bool,
    tenant_id: str,
) -> Dict[str, Any]:
    tool = repo.get_tool_by_id(tool_id)
    if tool is None:
        raise ValueError("Tool not found")
    # Verify server belongs to tenant
    get_server(str(tool["server_id"]), tenant_id)
    repo.set_tool_enabled(tool_id, enabled)
    return repo.get_tool_by_id(tool_id)


def get_available_servers_for_tenant(tenant_id: str) -> List[Dict[str, Any]]:
    """Return enabled servers for a tenant, suitable for /api/mcp/available."""
    servers = repo.list_by_tenant(tenant_id)
    return [s for s in servers if s["is_enabled"]]
