"""
biz_mcp/caller/api.py — API for MCP tool invocation.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from base_framework.base.security import CurrentUser
from biz_auth.deps import require_permission
from ..server.service import get_available_servers_for_tenant

from . import service as caller_svc

log = logging.getLogger(__name__)
router = APIRouter()


class ToolCallRequest(BaseModel):
    server_id: str
    tool_name: str
    arguments: Dict[str, Any] = {}


class ToolCallResponse(BaseModel):
    success: bool
    result: Any
    latency_ms: int


class AvailableServerResponse(BaseModel):
    id: str
    name: str
    identifier: str
    description: str
    tools: list[dict]


@router.post("/call", response_model=ToolCallResponse)
async def call_tool(
    req: ToolCallRequest,
    user: CurrentUser = Depends(require_permission("mcp:use")),
):
    try:
        result = await caller_svc.call_tool(
            server_id=req.server_id,
            tool_name=req.tool_name,
            arguments=req.arguments,
            tenant_id=user.tenant_id,
        )
        return ToolCallResponse(**result)
    except caller_svc.MCPServerDisabledError:
        raise HTTPException(status_code=400, detail="MCP Server is disabled")
    except caller_svc.MCPToolDisabledError:
        raise HTTPException(status_code=400, detail="MCP Tool is disabled")
    except caller_svc.MCPToolCallError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/available", response_model=list[AvailableServerResponse])
async def get_available(
    user: CurrentUser = Depends(require_permission("mcp:use")),
):
    """
    Return enabled MCP Servers and their tools for the current tenant.
    Used by the frontend to populate the tool picker.
    """
    servers = get_available_servers_for_tenant(user.tenant_id)
    from biz_mcp.server import repository as server_repo

    result = []
    for s in servers:
        tools = server_repo.list_tools_by_server(str(s["id"]))
        enabled_tools = [
            {
                "tool_name": t["tool_name"],
                "description": t["description"] or "",
                "input_schema": t["input_schema"] or {},
            }
            for t in tools
            if t["is_enabled"]
        ]
        result.append(
            AvailableServerResponse(
                id=str(s["id"]),
                name=s["name"],
                identifier=s["identifier"],
                description=s["description"] or "",
                tools=enabled_tools,
            )
        )
    return result
