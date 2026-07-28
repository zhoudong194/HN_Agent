"""
biz_auth/user/api.py — Authentication and user management API.
"""

from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from base_framework.base.security import CurrentUser
from biz_auth.deps import require_permission, require_user

from biz_auth.user.service import (
    AuthenticationError,
    EmailAlreadyExistsError,
    InvalidRoleError,
    UserNotFoundError,
    authenticate,
    create_new_user,
    deactivate_user,
    list_tenant_users,
    load_current_user,
    update_user,
)
from biz_auth.user.schema import (
    LoginRequest,
    LoginResponse,
    MeResponse,
    UserCreateRequest,
    UserInfo,
    UserUpdateRequest,
)
from biz_auth.user import repository as user_repo

log = logging.getLogger(__name__)
router = APIRouter()


# ----------------------------------------------------------------------
# /auth/*
# ----------------------------------------------------------------------
@router.post("/auth/login", response_model=LoginResponse)
async def login(req: LoginRequest):
    try:
        token, current_user = authenticate(req.email, req.password)
    except AuthenticationError:
        raise HTTPException(status_code=401, detail="invalid credentials")

    return LoginResponse(
        access_token=token,
        user=MeResponse(
            id=current_user.user_id,
            email=current_user.email,
            display_name=current_user.display_name,
            tenant_id=current_user.tenant_id,
            roles=current_user.roles,
            permissions=sorted(current_user.permissions),
            is_admin=current_user.is_admin(),
        ),
    )


@router.get("/auth/me", response_model=MeResponse)
async def me(user: CurrentUser = Depends(require_user)):
    return MeResponse(
        id=user.user_id,
        email=user.email,
        display_name=user.display_name,
        tenant_id=user.tenant_id,
        roles=user.roles,
        permissions=sorted(user.permissions),
        is_admin=user.is_admin(),
    )


@router.post("/auth/logout", status_code=204)
async def logout():
    return None


# ----------------------------------------------------------------------
# /admin/users
# ----------------------------------------------------------------------
@router.get("/admin/users", response_model=List[UserInfo])
async def list_users(admin: CurrentUser = Depends(require_permission("rbac:manage"))):
    users = list_tenant_users(admin.tenant_id)
    return [
        UserInfo(
            id=u["id"],
            email=u["email"],
            display_name=u["display_name"],
            is_active=u["is_active"],
            tenant_id=u["tenant_id"],
            role_ids=u["role_ids"],
            role_names=u["role_names"],
            created_at=u["created_at"],
        )
        for u in users
    ]


@router.post("/admin/users", response_model=UserInfo, status_code=201)
async def create_user(
    req: UserCreateRequest,
    admin: CurrentUser = Depends(require_permission("rbac:manage")),
):
    try:
        new_user = create_new_user(
            tenant_id=admin.tenant_id,
            email=req.email,
            display_name=req.display_name,
            password=req.password,
            admin=admin,
        )
    except EmailAlreadyExistsError:
        raise HTTPException(status_code=409, detail="email already exists")
    except InvalidRoleError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return UserInfo(
        id=new_user["id"],
        email=new_user["email"],
        display_name=new_user["display_name"],
        is_active=True,
        tenant_id=new_user["tenant_id"],
        role_ids=[],
        role_names=[],
        created_at=new_user["created_at"],
    )


@router.patch("/admin/users/{user_id}", response_model=UserInfo)
async def update_user_api(
    user_id: str,
    req: UserUpdateRequest,
    admin: CurrentUser = Depends(require_permission("rbac:manage")),
):
    try:
        updated = update_user(
            user_id=user_id,
            admin=admin,
            role_ids=req.role_ids,
            is_active=req.is_active,
        )
    except UserNotFoundError:
        raise HTTPException(status_code=404, detail="user not found")
    except InvalidRoleError as e:
        raise HTTPException(status_code=400, detail=str(e))

    role_ids = user_repo.get_user_role_ids(user_id)
    return UserInfo(
        id=updated["id"],
        email=updated["email"],
        display_name=updated["display_name"],
        is_active=updated["is_active"],
        tenant_id=updated["tenant_id"],
        role_ids=role_ids,
        role_names=[],
        created_at=str(updated.get("created_at", "")),
    )


@router.delete("/admin/users/{user_id}", status_code=204)
async def delete_user(
    user_id: str,
    admin: CurrentUser = Depends(require_permission("rbac:manage")),
):
    if str(admin.user_id) == user_id:
        raise HTTPException(status_code=400, detail="cannot delete yourself")
    try:
        deactivate_user(user_id, admin)
    except UserNotFoundError:
        raise HTTPException(status_code=404, detail="user not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return None
