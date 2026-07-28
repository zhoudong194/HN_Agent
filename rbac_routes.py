"""
rbac_routes.py — /api/auth/* and /api/admin/* endpoints.

Mounted by server.py with prefix /api. Every admin route is guarded by
require_permission("rbac:manage"), so a member attempting these gets 403.

Routes
------
POST   /api/auth/login
GET    /api/auth/me
POST   /api/auth/logout      (no-op; client discards the token)

GET    /api/admin/users
POST   /api/admin/users
DELETE /api/admin/users/{id}
PATCH  /api/admin/users/{id}        (assign roles)

GET    /api/admin/roles
POST   /api/admin/roles
PATCH  /api/admin/roles/{id}
DELETE /api/admin/roles/{id}

GET    /api/admin/permissions       (catalog read)
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from auth import (
    CurrentUser,
    create_access_token,
    hash_password,
    verify_password,
)
from database import _PooledConn
from rbac import invalidate_user_cache, require_permission, require_user

log = logging.getLogger(__name__)
router = APIRouter()


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _row_to_dict(cur, row) -> Dict[str, Any]:
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


def _list_permission_catalog() -> List[Dict[str, str]]:
    with _PooledConn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT key, description FROM rbac.permissions ORDER BY key")
        return [{"key": k, "description": d} for k, d in cur.fetchall()]


def _user_role_ids(user_id: str) -> List[str]:
    with _PooledConn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT role_id FROM rbac.user_roles WHERE user_id=%s ORDER BY role_id",
            (user_id,),
        )
        return [str(r[0]) for r in cur.fetchall()]


# ----------------------------------------------------------------------
# Schemas
# ----------------------------------------------------------------------
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


class PermissionInfo(BaseModel):
    key: str
    description: str


# ----------------------------------------------------------------------
# /api/auth/*
# ----------------------------------------------------------------------
@router.post("/auth/login", response_model=LoginResponse)
async def login(req: LoginRequest):
    with _PooledConn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, tenant_id, email, display_name, pw_hash, is_active "
            "FROM rbac.users WHERE email=%s",
            (req.email.lower(),),
        )
        row = cur.fetchone()
    if not row or not row[5]:
        raise HTTPException(status_code=401, detail="invalid credentials")
    user_id, tenant_id, email, display_name, pw_hash, is_active = row
    if not verify_password(req.password, pw_hash):
        raise HTTPException(status_code=401, detail="invalid credentials")

    # Load roles / permissions via the same path rbac.require_user uses
    from auth import load_user  # local import to keep auth.py lean at import time
    user = load_user(str(user_id))
    if user is None:
        raise HTTPException(status_code=401, detail="user unavailable")

    token = create_access_token(
        user_id=str(user_id),
        tenant_id=str(tenant_id),
        email=email,
        roles=user.roles,
        permissions=list(user.permissions),
    )
    return LoginResponse(
        access_token=token,
        user=MeResponse(
            id=str(user_id),
            email=email,
            display_name=display_name,
            tenant_id=str(tenant_id),
            roles=user.roles,
            permissions=sorted(user.permissions),
            is_admin=user.is_admin(),
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
    # Stateless JWT: the server keeps no session, so logout is a client-only
    # concern (delete the token). Returning 204 keeps the contract clean.
    return None


# ----------------------------------------------------------------------
# /api/admin/permissions  (read-only catalog)
# ----------------------------------------------------------------------
@router.get("/admin/permissions", response_model=List[PermissionInfo])
async def list_permissions(_: CurrentUser = Depends(require_permission("rbac:manage"))):
    return [PermissionInfo(**p) for p in _list_permission_catalog()]


# ----------------------------------------------------------------------
# /api/admin/users
# ----------------------------------------------------------------------
@router.get("/admin/users", response_model=List[UserInfo])
async def list_users(admin: CurrentUser = Depends(require_permission("rbac:manage"))):
    with _PooledConn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT u.id, u.email, u.display_name, u.is_active, u.tenant_id,
                   u.created_at,
                   COALESCE(array_agg(r.name) FILTER (WHERE r.name IS NOT NULL), '{}') AS role_names,
                   COALESCE(array_agg(r.id::text)   FILTER (WHERE r.id   IS NOT NULL), '{}') AS role_ids
            FROM rbac.users u
            LEFT JOIN rbac.user_roles ur ON ur.user_id = u.id
            LEFT JOIN rbac.roles r ON r.id = ur.role_id
            WHERE u.tenant_id = %s
            GROUP BY u.id
            ORDER BY u.created_at ASC
            """,
            (admin.tenant_id,),
        )
        rows = cur.fetchall()
    return [
        UserInfo(
            id=str(r[0]),
            email=r[1],
            display_name=r[2],
            is_active=bool(r[3]),
            tenant_id=str(r[4]),
            role_ids=list(r[7]),
            role_names=list(r[6]),
            created_at=str(r[5]),
        )
        for r in rows
    ]


@router.post("/admin/users", response_model=UserInfo, status_code=201)
async def create_user(
    req: UserCreateRequest,
    admin: CurrentUser = Depends(require_permission("rbac:manage")),
):
    new_id = str(uuid.uuid4())
    pw_hash = hash_password(req.password)

    with _PooledConn() as conn:
        cur = conn.cursor()
        # Uniqueness check (email is globally unique)
        cur.execute("SELECT 1 FROM rbac.users WHERE email=%s", (req.email.lower(),))
        if cur.fetchone():
            raise HTTPException(status_code=409, detail="email already exists")

        # Validate that all role_ids belong to this tenant
        if req.role_ids:
            cur.execute(
                "SELECT id FROM rbac.roles WHERE tenant_id=%s AND id = ANY(%s::uuid[])",
                (admin.tenant_id, req.role_ids),
            )
            valid = {str(r[0]) for r in cur.fetchall()}
            bad = set(req.role_ids) - valid
            if bad:
                raise HTTPException(
                    status_code=400,
                    detail=f"role_ids not in your tenant: {sorted(bad)}",
                )

        cur.execute(
            "INSERT INTO rbac.users(id, tenant_id, email, display_name, pw_hash) "
            "VALUES (%s,%s,%s,%s,%s) RETURNING created_at",
            (new_id, admin.tenant_id, req.email.lower(), req.display_name, pw_hash),
        )
        created_at = cur.fetchone()[0]

        for rid in req.role_ids:
            cur.execute(
                "INSERT INTO rbac.user_roles(user_id, role_id) VALUES (%s,%s)",
                (new_id, rid),
            )
        conn.commit()

    return UserInfo(
        id=new_id,
        email=req.email.lower(),
        display_name=req.display_name,
        is_active=True,
        tenant_id=admin.tenant_id,
        role_ids=req.role_ids,
        role_names=[],
        created_at=str(created_at),
    )


@router.patch("/admin/users/{user_id}", response_model=UserInfo)
async def update_user(
    user_id: str,
    req: UserUpdateRequest,
    admin: CurrentUser = Depends(require_permission("rbac:manage")),
):
    with _PooledConn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT tenant_id, email, display_name, is_active, created_at "
            "FROM rbac.users WHERE id=%s",
            (user_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="user not found")
        tenant_id, email, name, is_active, created_at = row
        if str(tenant_id) != admin.tenant_id:
            raise HTTPException(status_code=404, detail="user not found")

        if req.is_active is not None and req.is_active != is_active:
            cur.execute(
                "UPDATE rbac.users SET is_active=%s WHERE id=%s",
                (req.is_active, user_id),
            )

        if req.role_ids is not None:
            cur.execute(
                "SELECT id FROM rbac.roles WHERE tenant_id=%s AND id = ANY(%s::uuid[])",
                (admin.tenant_id, req.role_ids),
            )
            valid = {str(r[0]) for r in cur.fetchall()}
            bad = set(req.role_ids) - valid
            if bad:
                raise HTTPException(
                    status_code=400,
                    detail=f"role_ids not in your tenant: {sorted(bad)}",
                )
            cur.execute("DELETE FROM rbac.user_roles WHERE user_id=%s", (user_id,))
            for rid in req.role_ids:
                cur.execute(
                    "INSERT INTO rbac.user_roles(user_id, role_id) VALUES (%s,%s)",
                    (user_id, rid),
                )
        conn.commit()

    invalidate_user_cache(user_id)

    # Refresh
    role_ids_now = _user_role_ids(user_id)
    return UserInfo(
        id=user_id,
        email=email,
        display_name=name,
        is_active=req.is_active if req.is_active is not None else is_active,
        tenant_id=admin.tenant_id,
        role_ids=role_ids_now,
        role_names=[],
        created_at=str(created_at),
    )


@router.delete("/admin/users/{user_id}", status_code=204)
async def delete_user(
    user_id: str,
    admin: CurrentUser = Depends(require_permission("rbac:manage")),
):
    if str(admin.user_id) == user_id:
        raise HTTPException(status_code=400, detail="cannot delete yourself")
    with _PooledConn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT tenant_id FROM rbac.users WHERE id=%s",
            (user_id,),
        )
        row = cur.fetchone()
        if not row or str(row[0]) != admin.tenant_id:
            raise HTTPException(status_code=404, detail="user not found")
        cur.execute(
            "UPDATE rbac.users SET is_active=false WHERE id=%s",
            (user_id,),
        )
        conn.commit()
    invalidate_user_cache(user_id)
    return None


# ----------------------------------------------------------------------
# /api/admin/roles
# ----------------------------------------------------------------------
def _list_roles_for_tenant(tenant_id: str) -> List[RoleInfo]:
    with _PooledConn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT r.id, r.name, r.is_system, r.tenant_id,
                   COALESCE(array_agg(rp.permission_key ORDER BY rp.permission_key)
                            FILTER (WHERE rp.permission_key IS NOT NULL), '{}') AS perms,
                   (SELECT COUNT(*) FROM rbac.user_roles ur WHERE ur.role_id = r.id) AS ucount
            FROM rbac.roles r
            LEFT JOIN rbac.role_permissions rp ON rp.role_id = r.id
            WHERE r.tenant_id = %s
            GROUP BY r.id
            ORDER BY r.is_system DESC, r.name ASC
            """,
            (tenant_id,),
        )
        rows = cur.fetchall()
    return [
        RoleInfo(
            id=str(r[0]),
            name=r[1],
            is_system=bool(r[2]),
            tenant_id=str(r[3]),
            permission_keys=list(r[4]),
            user_count=int(r[5]),
        )
        for r in rows
    ]


@router.get("/admin/roles", response_model=List[RoleInfo])
async def list_roles(admin: CurrentUser = Depends(require_permission("rbac:manage"))):
    return _list_roles_for_tenant(admin.tenant_id)


@router.post("/admin/roles", response_model=RoleInfo, status_code=201)
async def create_role(
    req: RoleCreateRequest,
    admin: CurrentUser = Depends(require_permission("rbac:manage")),
):
    new_id = str(uuid.uuid4())

    # Validate every permission key exists in the catalog
    valid_perms = {p["key"] for p in _list_permission_catalog()}
    bad = [k for k in req.permission_keys if k not in valid_perms]
    if bad:
        raise HTTPException(status_code=400, detail=f"unknown permission_keys: {bad}")

    with _PooledConn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM rbac.roles WHERE tenant_id=%s AND name=%s",
            (admin.tenant_id, req.name),
        )
        if cur.fetchone():
            raise HTTPException(status_code=409, detail="role name already exists")

        cur.execute(
            "INSERT INTO rbac.roles(id, tenant_id, name, is_system) "
            "VALUES (%s,%s,%s,false) RETURNING id",
            (new_id, admin.tenant_id, req.name),
        )
        for pkey in req.permission_keys:
            cur.execute(
                "INSERT INTO rbac.role_permissions(role_id, permission_key) VALUES (%s,%s)",
                (new_id, pkey),
            )
        conn.commit()

    invalidate_user_cache()
    return RoleInfo(
        id=new_id,
        name=req.name,
        is_system=False,
        tenant_id=admin.tenant_id,
        permission_keys=req.permission_keys,
        user_count=0,
    )


@router.delete("/admin/roles/{role_id}", status_code=204)
async def delete_role(
    role_id: str,
    admin: CurrentUser = Depends(require_permission("rbac:manage")),
):
    with _PooledConn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT tenant_id, is_system FROM rbac.roles WHERE id=%s",
            (role_id,),
        )
        row = cur.fetchone()
        if not row or str(row[0]) != admin.tenant_id:
            raise HTTPException(status_code=404, detail="role not found")
        if row[1]:
            raise HTTPException(status_code=400, detail="cannot delete system role")
        # ON DELETE CASCADE removes role_permissions and user_roles rows
        cur.execute("DELETE FROM rbac.roles WHERE id=%s", (role_id,))
        conn.commit()
    invalidate_user_cache()
    return None


@router.patch("/admin/roles/{role_id}", response_model=RoleInfo)
async def update_role(
    role_id: str,
    req: RoleUpdateRequest,
    admin: CurrentUser = Depends(require_permission("rbac:manage")),
):
    with _PooledConn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT name, is_system, tenant_id FROM rbac.roles WHERE id=%s",
            (role_id,),
        )
        row = cur.fetchone()
        if not row or str(row[2]) != admin.tenant_id:
            raise HTTPException(status_code=404, detail="role not found")
        name, is_system, _ = row

        if req.name is not None and req.name != name:
            cur.execute(
                "SELECT 1 FROM rbac.roles WHERE tenant_id=%s AND name=%s AND id<>%s",
                (admin.tenant_id, req.name, role_id),
            )
            if cur.fetchone():
                raise HTTPException(status_code=409, detail="role name already exists")
            cur.execute("UPDATE rbac.roles SET name=%s WHERE id=%s", (req.name, role_id))

        if req.permission_keys is not None:
            valid_perms = {p["key"] for p in _list_permission_catalog()}
            bad = [k for k in req.permission_keys if k not in valid_perms]
            if bad:
                raise HTTPException(status_code=400, detail=f"unknown permission_keys: {bad}")
            cur.execute("DELETE FROM rbac.role_permissions WHERE role_id=%s", (role_id,))
            for pkey in req.permission_keys:
                cur.execute(
                    "INSERT INTO rbac.role_permissions(role_id, permission_key) VALUES (%s,%s)",
                    (role_id, pkey),
                )
        conn.commit()

    invalidate_user_cache()
    # Return the single updated role
    refreshed = [r for r in _list_roles_for_tenant(admin.tenant_id) if r.id == role_id]
    if not refreshed:
        raise HTTPException(status_code=404, detail="role disappeared")
    return refreshed[0]