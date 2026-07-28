"""
biz_auth/user/schema.py — User-related Pydantic schemas.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class MeResponse(BaseModel):
    id: str
    email: str
    display_name: str
    tenant_id: str
    roles: List[str]
    permissions: List[str]
    is_admin: bool


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: MeResponse


class UserInfo(BaseModel):
    id: str
    email: str
    display_name: str
    is_active: bool
    tenant_id: str
    role_ids: List[str]
    role_names: List[str]
    created_at: str


class UserCreateRequest(BaseModel):
    email: EmailStr
    display_name: str = Field(..., min_length=1, max_length=120)
    password: str = Field(..., min_length=8, max_length=128)
    role_ids: List[str] = Field(default_factory=list)


class UserUpdateRequest(BaseModel):
    role_ids: Optional[List[str]] = None
    is_active: Optional[bool] = None
