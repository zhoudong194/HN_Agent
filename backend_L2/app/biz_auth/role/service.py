"""
biz_auth/role/service.py — Role business logic.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from biz_auth.deps import invalidate_user_cache
from biz_auth.role.repository import (
    create_role as repo_create_role,
    delete_role as repo_delete_role,
    find_role_by_id,
    list_permission_catalog,
    list_roles_for_tenant,
    role_name_exists,
    update_role as repo_update_role,
)

log = logging.getLogger(__name__)


class RoleNotFoundError(Exception):
    """Raised when role is not found."""


class SystemRoleError(Exception):
    """Raised when trying to modify a system role."""


class RoleNameExistsError(Exception):
    """Raised when role name already exists."""


class InvalidPermissionKeyError(Exception):
    """Raised when permission key is not in catalog."""


def list_permissions() -> List[dict]:
    """Return the permission catalog."""
    return list_permission_catalog()


def list_tenant_roles(tenant_id: str) -> List[dict]:
    """List all roles for a tenant."""
    return list_roles_for_tenant(tenant_id)


def create_new_role(
    tenant_id: str,
    name: str,
    permission_keys: List[str],
) -> dict:
    """Create a new role with permissions."""
    _validate_permission_keys(permission_keys)

    if role_name_exists(tenant_id, name):
        raise RoleNameExistsError("role name already exists")

    new_id = repo_create_role(tenant_id, name, permission_keys)
    log.info("Created role %s (%s)", new_id, name)

    return {
        "id": new_id,
        "name": name,
        "is_system": False,
        "tenant_id": tenant_id,
        "permission_keys": permission_keys,
        "user_count": 0,
    }


def update_existing_role(
    role_id: str,
    tenant_id: str,
    name: Optional[str] = None,
    permission_keys: Optional[List[str]] = None,
) -> dict:
    """Update an existing role."""
    role = find_role_by_id(role_id)
    if role is None or role["tenant_id"] != tenant_id:
        raise RoleNotFoundError("role not found")

    if role["is_system"]:
        raise SystemRoleError("cannot modify system role")

    if name is not None and name != role["name"]:
        if role_name_exists(tenant_id, name, exclude_role_id=role_id):
            raise RoleNameExistsError("role name already exists")

    if permission_keys is not None:
        _validate_permission_keys(permission_keys)

    repo_update_role(role_id, name=name, permission_keys=permission_keys)
    invalidate_user_cache()
    log.info("Updated role %s", role_id)

    updated_roles = list_roles_for_tenant(tenant_id)
    return next(r for r in updated_roles if r["id"] == role_id)


def delete_existing_role(role_id: str, tenant_id: str) -> None:
    """Delete a role."""
    role = find_role_by_id(role_id)
    if role is None or role["tenant_id"] != tenant_id:
        raise RoleNotFoundError("role not found")

    if role["is_system"]:
        raise SystemRoleError("cannot delete system role")

    repo_delete_role(role_id)
    invalidate_user_cache()
    log.info("Deleted role %s", role_id)


def _validate_permission_keys(keys: List[str]) -> None:
    """Validate that all permission keys exist in the catalog."""
    catalog = list_permission_catalog()
    valid = {p["key"] for p in catalog}
    bad = [k for k in keys if k not in valid]
    if bad:
        raise InvalidPermissionKeyError(f"unknown permission_keys: {bad}")
