"""
biz_auth/role/api.py — Role management API.
"""

from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status

from base_framework.base.security import CurrentUser
from biz_auth.deps import require_permission
from biz_auth.role.service import (
    InvalidPermissionKeyError,
    RoleNameExistsError,
    RoleNotFoundError,
    SystemRoleError,
    create_new_role,
    delete_existing_role,
    list_permissions,
    list_tenant_roles,
    update_existing_role,
)
from biz_auth.role.schema import (
    RoleCreateRequest,
    RoleInfo,
    RoleUpdateRequest,
)

log = logging.getLogger(__name__)
router = APIRouter()


@router.get("/admin/permissions")
async def list_permissions_api(_: CurrentUser = Depends(require_permission("rbac:manage"))):
    return [{"key": p["key"], "description": p["description"]} for p in list_permissions()]


@router.get("/admin/roles", response_model=List[RoleInfo])
async def list_roles(admin: CurrentUser = Depends(require_permission("rbac:manage"))):
    roles = list_tenant_roles(admin.tenant_id)
    return [RoleInfo(**r) for r in roles]


@router.post("/admin/roles", response_model=RoleInfo, status_code=201)
async def create_role(
    req: RoleCreateRequest,
    admin: CurrentUser = Depends(require_permission("rbac:manage")),
):
    try:
        role = create_new_role(
            tenant_id=admin.tenant_id,
            name=req.name,
            permission_keys=req.permission_keys,
        )
    except RoleNameExistsError:
        raise HTTPException(status_code=409, detail="role name already exists")
    except InvalidPermissionKeyError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return RoleInfo(**role)


@router.delete("/admin/roles/{role_id}", status_code=204)
async def delete_role(
    role_id: str,
    admin: CurrentUser = Depends(require_permission("rbac:manage")),
):
    try:
        delete_existing_role(role_id, admin.tenant_id)
    except RoleNotFoundError:
        raise HTTPException(status_code=404, detail="role not found")
    except SystemRoleError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return None


@router.patch("/admin/roles/{role_id}", response_model=RoleInfo)
async def update_role(
    role_id: str,
    req: RoleUpdateRequest,
    admin: CurrentUser = Depends(require_permission("rbac:manage")),
):
    try:
        role = update_existing_role(
            role_id=role_id,
            tenant_id=admin.tenant_id,
            name=req.name,
            permission_keys=req.permission_keys,
        )
    except RoleNotFoundError:
        raise HTTPException(status_code=404, detail="role not found")
    except RoleNameExistsError:
        raise HTTPException(status_code=409, detail="role name already exists")
    except SystemRoleError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except InvalidPermissionKeyError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return RoleInfo(**role)
