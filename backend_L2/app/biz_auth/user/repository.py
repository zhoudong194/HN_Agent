"""
biz_auth/user/repository.py — User data access layer.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from base_framework.base.db_engine import PooledConn


def find_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    """Look up a user by email. Returns None if not found."""
    with PooledConn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, tenant_id, email, display_name, pw_hash, is_active "
            "FROM rbac.users WHERE email=%s",
            (email.lower(),),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "id": str(row[0]),
            "tenant_id": str(row[1]),
            "email": row[2],
            "display_name": row[3],
            "pw_hash": row[4],
            "is_active": row[5],
        }


def find_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    """Look up a user by id. Returns None if not found."""
    with PooledConn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, tenant_id, email, display_name, pw_hash, is_active "
            "FROM rbac.users WHERE id=%s",
            (user_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "id": str(row[0]),
            "tenant_id": str(row[1]),
            "email": row[2],
            "display_name": row[3],
            "pw_hash": row[4],
            "is_active": row[5],
        }


def list_user_roles(user_id: str) -> List[str]:
    """Get role names for a user."""
    with PooledConn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT r.name FROM rbac.roles r "
            "JOIN rbac.user_roles ur ON ur.role_id = r.id "
            "WHERE ur.user_id=%s",
            (user_id,),
        )
        return [r[0] for r in cur.fetchall()]


def list_user_permissions(user_id: str) -> set:
    """Get effective permission keys for a user."""
    with PooledConn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT rp.permission_key FROM rbac.role_permissions rp "
            "JOIN rbac.user_roles ur ON ur.role_id = rp.role_id "
            "WHERE ur.user_id=%s",
            (user_id,),
        )
        return {r[0] for r in cur.fetchall()}


def create_user(
    tenant_id: str,
    email: str,
    display_name: str,
    pw_hash: str,
    role_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Create a new user and assign roles."""
    new_id = str(uuid.uuid4())
    role_ids = role_ids or []

    with PooledConn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO rbac.users(id, tenant_id, email, display_name, pw_hash) "
            "VALUES (%s,%s,%s,%s,%s) RETURNING created_at",
            (new_id, tenant_id, email.lower(), display_name, pw_hash),
        )
        created_at = cur.fetchone()[0]

        for rid in role_ids:
            cur.execute(
                "INSERT INTO rbac.user_roles(user_id, role_id) VALUES (%s,%s)",
                (new_id, rid),
            )
        conn.commit()

    return {
        "id": new_id,
        "tenant_id": tenant_id,
        "email": email.lower(),
        "display_name": display_name,
        "created_at": str(created_at),
    }


def email_exists(email: str) -> bool:
    """Check if email is already registered."""
    with PooledConn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM rbac.users WHERE email=%s", (email.lower(),))
        return cur.fetchone() is not None


def list_users_for_tenant(tenant_id: str) -> List[Dict[str, Any]]:
    """List all users in a tenant with roles."""
    with PooledConn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT u.id, u.email, u.display_name, u.is_active, u.tenant_id,
                   u.created_at,
                   COALESCE(array_agg(r.name) FILTER (WHERE r.name IS NOT NULL), '{}') AS role_names,
                   COALESCE(array_agg(r.id::text) FILTER (WHERE r.id IS NOT NULL), '{}') AS role_ids
            FROM rbac.users u
            LEFT JOIN rbac.user_roles ur ON ur.user_id = u.id
            LEFT JOIN rbac.roles r ON r.id = ur.role_id
            WHERE u.tenant_id = %s
            GROUP BY u.id
            ORDER BY u.created_at ASC
            """,
            (tenant_id,),
        )
        rows = cur.fetchall()
        return [
            {
                "id": str(r[0]),
                "email": r[1],
                "display_name": r[2],
                "is_active": bool(r[3]),
                "tenant_id": str(r[4]),
                "role_ids": list(r[7]),
                "role_names": list(r[6]),
                "created_at": str(r[5]),
            }
            for r in rows
        ]


def update_user_roles(user_id: str, role_ids: List[str]) -> None:
    """Replace user's role assignments."""
    with PooledConn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM rbac.user_roles WHERE user_id=%s", (user_id,))
        for rid in role_ids:
            cur.execute(
                "INSERT INTO rbac.user_roles(user_id, role_id) VALUES (%s,%s)",
                (user_id, rid),
            )
        conn.commit()


def set_user_active(user_id: str, is_active: bool) -> None:
    """Enable or disable a user account."""
    with PooledConn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE rbac.users SET is_active=%s WHERE id=%s",
            (is_active, user_id),
        )
        conn.commit()


def get_user_role_ids(user_id: str) -> List[str]:
    """Get role IDs for a user."""
    with PooledConn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT role_id FROM rbac.user_roles WHERE user_id=%s ORDER BY role_id",
            (user_id,),
        )
        return [str(r[0]) for r in cur.fetchall()]
