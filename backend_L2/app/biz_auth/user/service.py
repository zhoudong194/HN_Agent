"""
biz_auth/user/service.py — User business logic.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from base_framework.base.security import (
    CurrentUser,
    create_access_token,
    hash_password,
    verify_password,
)
from base_framework.base.db_engine import PooledConn

from biz_auth.user.repository import (
    email_exists,
    find_user_by_email,
    find_user_by_id,
    list_user_roles,
    list_user_permissions,
    create_user as repo_create_user,
    list_users_for_tenant,
    update_user_roles,
    set_user_active,
    get_user_role_ids,
)

log = logging.getLogger(__name__)


class AuthenticationError(Exception):
    """Raised when authentication fails."""


class UserNotFoundError(Exception):
    """Raised when a user is not found."""


class EmailAlreadyExistsError(Exception):
    """Raised when attempting to create a user with existing email."""


class InvalidRoleError(Exception):
    """Raised when role_ids are invalid."""


def load_current_user(user_id: str) -> Optional[CurrentUser]:
    """
    Look up a user by id and assemble their roles + effective permissions.
    Returns None if the user is missing or inactive.
    """
    user = find_user_by_id(user_id)
    if user is None:
        return None
    if not user["is_active"]:
        return None

    roles = list_user_roles(user_id)
    perms = list_user_permissions(user_id)

    return CurrentUser(
        user_id=user["id"],
        tenant_id=user["tenant_id"],
        email=user["email"],
        display_name=user["display_name"],
        is_active=bool(user["is_active"]),
        roles=roles,
        permissions=perms,
    )


def authenticate(email: str, password: str) -> tuple[str, CurrentUser]:
    """
    Authenticate user by email and password.
    Returns (access_token, current_user).
    Raises AuthenticationError on failure.
    """
    user = find_user_by_email(email)
    if user is None or not user["is_active"]:
        raise AuthenticationError("invalid credentials")

    if not verify_password(password, user["pw_hash"]):
        raise AuthenticationError("invalid credentials")

    roles = list_user_roles(user["id"])
    perms = list_user_permissions(user["id"])

    current_user = CurrentUser(
        user_id=user["id"],
        tenant_id=user["tenant_id"],
        email=user["email"],
        display_name=user["display_name"],
        is_active=True,
        roles=roles,
        permissions=perms,
    )

    token = create_access_token(
        user_id=user["id"],
        tenant_id=user["tenant_id"],
        email=user["email"],
        roles=roles,
        permissions=list(perms),
    )

    return token, current_user


def create_new_user(
    tenant_id: str,
    email: str,
    display_name: str,
    password: str,
    admin: CurrentUser,
) -> dict:
    """Create a new user. Admin context required for tenant validation."""
    if email_exists(email):
        raise EmailAlreadyExistsError("email already exists")

    _validate_role_ids(admin.tenant_id, admin.tenant_id, [])

    pw_hash = hash_password(password)
    new_user = repo_create_user(
        tenant_id=tenant_id,
        email=email,
        display_name=display_name,
        pw_hash=pw_hash,
    )
    log.info("Created user %s (%s)", new_user["id"], email)
    return new_user


def list_tenant_users(tenant_id: str) -> List[dict]:
    """List all users in a tenant."""
    return list_users_for_tenant(tenant_id)


def update_user(
    user_id: str,
    admin: CurrentUser,
    role_ids: Optional[List[str]] = None,
    is_active: Optional[bool] = None,
) -> dict:
    """Update user roles and active status."""
    user = find_user_by_id(user_id)
    if user is None:
        raise UserNotFoundError("user not found")
    if user["tenant_id"] != admin.tenant_id:
        raise UserNotFoundError("user not found")

    if role_ids is not None:
        _validate_role_ids(admin.tenant_id, user_id, role_ids)
        update_user_roles(user_id, role_ids)

    if is_active is not None:
        set_user_active(user_id, is_active)

    current_roles = get_user_role_ids(user_id)
    return {
        **user,
        "role_ids": current_roles,
    }


def deactivate_user(user_id: str, admin: CurrentUser) -> None:
    """Soft-delete a user (set is_active=False)."""
    if user_id == admin.user_id:
        raise ValueError("cannot delete yourself")
    user = find_user_by_id(user_id)
    if user is None or user["tenant_id"] != admin.tenant_id:
        raise UserNotFoundError("user not found")
    set_user_active(user_id, False)


def _validate_role_ids(tenant_id: str, user_id: str, role_ids: List[str]) -> None:
    """Validate that all role_ids belong to the tenant."""
    if not role_ids:
        return
    with PooledConn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM rbac.roles WHERE tenant_id=%s AND id = ANY(%s::uuid[])",
            (tenant_id, role_ids),
        )
        valid = {str(r[0]) for r in cur.fetchall()}
        bad = set(role_ids) - valid
        if bad:
            raise InvalidRoleError(f"role_ids not in your tenant: {sorted(bad)}")
