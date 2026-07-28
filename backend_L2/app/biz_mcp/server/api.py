"""
biz_mcp/server/api.py — REST API for MCP Server management.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from base_framework.base.security import CurrentUser
from biz_auth.deps import require_permission

from . import service as svc
from .schema import (
    MCPServerCreateRequest,
    MCPServerResponse,
    MCPServerUpdateRequest,
    MCPToolResponse,
)

log = logging.getLogger(__name__)
router = APIRouter()


def _server_to_resp(s: Dict[str, Any]) -> MCPServerResponse:
    return MCPServerResponse(
        id=str(s["id"]),
        tenant_id=str(s["tenant_id"]),
        name=s["name"],
        identifier=s["identifier"],
        description=s["description"] or "",
        config_json=s["config_json"] or {},
        is_enabled=s["is_enabled"],
        created_by=str(s["created_by"]) if s.get("created_by") else None,
        created_at=str(s["created_at"]),
        updated_at=str(s["updated_at"]),
    )


def _tool_to_resp(t: Dict[str, Any]) -> MCPToolResponse:
    return MCPToolResponse(
        id=str(t["id"]),
        server_id=str(t["server_id"]),
        tool_name=t["tool_name"],
        description=t["description"] or "",
        input_schema=t["input_schema"] or {},
        is_enabled=t["is_enabled"],
        created_at=str(t["created_at"]),
    )


@router.get("/", response_model=list[MCPServerResponse])
async def list_servers(
    admin: CurrentUser = Depends(require_permission("mcp:manage")),
):
    servers = svc.list_servers(admin.tenant_id)
    return [_server_to_resp(s) for s in servers]


@router.post("/", response_model=MCPServerResponse, status_code=201)
async def create_server(
    req: MCPServerCreateRequest,
    admin: CurrentUser = Depends(require_permission("mcp:manage")),
):
    try:
        server = svc.create_server(
            tenant_id=admin.tenant_id,
            name=req.name,
            identifier=req.identifier,
            description=req.description,
            config_json=req.config_json,
            created_by=admin.user_id,
        )
        return _server_to_resp(server)
    except svc.MCPServerNotRegisteredError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except svc.MCPServerIdentifierExistsError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/{server_id}", response_model=MCPServerResponse)
async def get_server(
    server_id: str,
    admin: CurrentUser = Depends(require_permission("mcp:manage")),
):
    try:
        server = svc.get_server(server_id, admin.tenant_id)
        return _server_to_resp(server)
    except svc.MCPServerNotFoundError:
        raise HTTPException(status_code=404, detail="server not found")


@router.patch("/{server_id}", response_model=MCPServerResponse)
async def update_server(
    server_id: str,
    req: MCPServerUpdateRequest,
    admin: CurrentUser = Depends(require_permission("mcp:manage")),
):
    try:
        server = svc.update_server(
            server_id=server_id,
            tenant_id=admin.tenant_id,
            name=req.name,
            description=req.description,
            config_json=req.config_json,
        )
        return _server_to_resp(server)
    except svc.MCPServerNotFoundError:
        raise HTTPException(status_code=404, detail="server not found")


@router.post("/{server_id}/enable", response_model=MCPServerResponse)
async def enable_server(
    server_id: str,
    admin: CurrentUser = Depends(require_permission("mcp:manage")),
):
    try:
        server = svc.enable_server(server_id, admin.tenant_id)
        return _server_to_resp(server)
    except svc.MCPServerNotFoundError:
        raise HTTPException(status_code=404, detail="server not found")


@router.post("/{server_id}/disable", response_model=MCPServerResponse)
async def disable_server(
    server_id: str,
    admin: CurrentUser = Depends(require_permission("mcp:manage")),
):
    try:
        server = svc.disable_server(server_id, admin.tenant_id)
        return _server_to_resp(server)
    except svc.MCPServerNotFoundError:
        raise HTTPException(status_code=404, detail="server not found")


@router.delete("/{server_id}", status_code=204)
async def delete_server(
    server_id: str,
    admin: CurrentUser = Depends(require_permission("mcp:manage")),
):
    try:
        svc.delete_server(server_id, admin.tenant_id)
    except svc.MCPServerNotFoundError:
        raise HTTPException(status_code=404, detail="server not found")
    return None


@router.get("/{server_id}/tools", response_model=list[MCPToolResponse])
async def list_server_tools(
    server_id: str,
    admin: CurrentUser = Depends(require_permission("mcp:manage")),
):
    try:
        tools = svc.list_server_tools(server_id, admin.tenant_id)
        return [_tool_to_resp(t) for t in tools]
    except svc.MCPServerNotFoundError:
        raise HTTPException(status_code=404, detail="server not found")
