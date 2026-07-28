"""
biz_mcp/server/schema.py — Pydantic schemas for MCP Server.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class MCPServerCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    identifier: str = Field(..., min_length=1)
    description: str = Field(default="")
    config_json: Dict[str, Any] = Field(default_factory=dict)


class MCPServerUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    description: Optional[str] = None
    config_json: Optional[Dict[str, Any]] = None


class MCPServerResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    identifier: str
    description: str
    config_json: Dict[str, Any]
    is_enabled: bool
    created_by: Optional[str]
    created_at: str
    updated_at: str


class MCPToolResponse(BaseModel):
    id: str
    server_id: str
    tool_name: str
    description: str
    input_schema: Dict[str, Any]
    is_enabled: bool
    created_at: str
