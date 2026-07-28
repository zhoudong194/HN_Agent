"""
biz_auth/role/repository.py — Role data access layer.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List

from base_framework.base.db_engine import PooledConn


def list_permission_catalog() -> List[Dict[str, str]]:
    """Return all permission keys with descriptions."""
    with PooledConn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT key, description FROM rbac.permissions ORDER BY key")
        return [{"key": k, "description": d} for k, d in cur.fetchall()]


def list_roles_for_tenant(tenant_id: str) -> List[Dict[str, Any]]:
    """List all roles in a tenant with permission keys and user counts."""
    with PooledConn() as conn:
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
            {
                "id": str(r[0]),
                "name": r[1],
                "is_system": bool(r[2]),
                "tenant_id": str(r[3]),
                "permission_keys": list(r[4]),
                "user_count": int(r[5]),
            }
            for r in rows
        ]


def find_role_by_id(role_id: str) -> Optional[Dict[str, Any]]:
    """Find a role by ID. Returns None if not found."""
    with PooledConn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name, is_system, tenant_id FROM rbac.roles WHERE id=%s",
            (role_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "id": str(row[0]),
            "name": row[1],
            "is_system": bool(row[2]),
            "tenant_id": str(row[3]),
        }


def create_role(
    tenant_id: str,
    name: str,
    permission_keys: Optional[List[str]] = None,
) -> str:
    """Create a new role. Returns role_id."""
    new_id = str(uuid.uuid4())
    permission_keys = permission_keys or []

    with PooledConn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO rbac.roles(id, tenant_id, name, is_system) "
            "VALUES (%s,%s,%s,false) RETURNING id",
            (new_id, tenant_id, name),
        )
        for pkey in permission_keys:
            cur.execute(
                "INSERT INTO rbac.role_permissions(role_id, permission_key) VALUES (%s,%s)",
                (new_id, pkey),
            )
        conn.commit()
    return new_id


def update_role(
    role_id: str,
    name: Optional[str] = None,
    permission_keys: Optional[List[str]] = None,
) -> None:
    """Update role name and/or permissions."""
    with PooledConn() as conn:
        cur = conn.cursor()
        if name is not None:
            cur.execute(
                "UPDATE rbac.roles SET name=%s WHERE id=%s",
                (name, role_id),
            )
        if permission_keys is not None:
            cur.execute(
                "DELETE FROM rbac.role_permissions WHERE role_id=%s",
                (role_id,),
            )
            for pkey in permission_keys:
                cur.execute(
                    "INSERT INTO rbac.role_permissions(role_id, permission_key) VALUES (%s,%s)",
                    (role_id, pkey),
                )
        conn.commit()


def delete_role(role_id: str) -> bool:
    """Delete a role. Returns True if deleted."""
    with PooledConn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM rbac.roles WHERE id=%s", (role_id,))
        conn.commit()
        return cur.rowcount > 0


def role_name_exists(tenant_id: str, name: str, exclude_role_id: str = None) -> bool:
    """Check if role name exists in tenant."""
    with PooledConn() as conn:
        cur = conn.cursor()
        if exclude_role_id:
            cur.execute(
                "SELECT 1 FROM rbac.roles WHERE tenant_id=%s AND name=%s AND id<>%s",
                (tenant_id, name, exclude_role_id),
            )
        else:
            cur.execute(
                "SELECT 1 FROM rbac.roles WHERE tenant_id=%s AND name=%s",
                (tenant_id, name),
            )
        return cur.fetchone() is not None
