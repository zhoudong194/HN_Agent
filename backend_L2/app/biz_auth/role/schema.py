"""
biz_auth/role/schema.py — Role-related Pydantic schemas.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class RoleInfo(BaseModel):
    id: str
    name: str
    is_system: bool
    tenant_id: str
    permission_keys: List[str]
    user_count: int


class RoleCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=60)
    permission_keys: List[str] = Field(default_factory=list)


class RoleUpdateRequest(BaseModel):
    permission_keys: Optional[List[str]] = None
    name: Optional[str] = Field(default=None, min_length=1, max_length=60)
