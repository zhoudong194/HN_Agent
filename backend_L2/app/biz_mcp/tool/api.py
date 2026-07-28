"""
biz_mcp/tool/api.py — Tool-level management API (enable/disable individual tools).
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from base_framework.base.security import CurrentUser
from biz_auth.deps import require_permission

from ..server import repository as server_repo
from ..server.schema import MCPToolResponse
from ..server.service import set_tool_enabled

log = logging.getLogger(__name__)
router = APIRouter()


class ToolToggleRequest(BaseModel):
    enabled: bool


@router.get("/{tool_id}", response_model=MCPToolResponse)
async def get_tool(
    tool_id: str,
    admin: CurrentUser = Depends(require_permission("mcp:manage")),
):
    tool = server_repo.get_tool_by_id(tool_id)
    if tool is None:
        raise HTTPException(status_code=404, detail="tool not found")
    return MCPToolResponse(
        id=str(tool["id"]),
        server_id=str(tool["server_id"]),
        tool_name=tool["tool_name"],
        description=tool["description"] or "",
        input_schema=tool["input_schema"] or {},
        is_enabled=tool["is_enabled"],
        created_at=str(tool["created_at"]),
    )


@router.patch("/{tool_id}", response_model=MCPToolResponse)
async def toggle_tool(
    tool_id: str,
    req: ToolToggleRequest,
    admin: CurrentUser = Depends(require_permission("mcp:manage")),
):
    try:
        tool = set_tool_enabled(tool_id, req.enabled, admin.tenant_id)
        return MCPToolResponse(
            id=str(tool["id"]),
            server_id=str(tool["server_id"]),
            tool_name=tool["tool_name"],
            description=tool["description"] or "",
            input_schema=tool["input_schema"] or {},
            is_enabled=tool["is_enabled"],
            created_at=str(tool["created_at"]),
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="tool not found")
