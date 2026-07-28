"""
biz_mcp/server/repository.py — Data access layer for mcp_servers.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from base_framework.base.db_engine import PooledConn

log = logging.getLogger(__name__)


def _conn():
    from base_framework.base.db_engine import _conn as _raw_conn
    return _raw_conn()


def list_by_tenant(tenant_id: str) -> List[Dict[str, Any]]:
    with PooledConn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, tenant_id, name, identifier, description,
                   config_json, is_enabled, created_by, created_at, updated_at
            FROM rbac.mcp_servers
            WHERE tenant_id = %s
            ORDER BY created_at DESC
            """,
            (tenant_id,),
        )
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        return [dict(zip(cols, r)) for r in rows]


def get_by_id(server_id: str) -> Optional[Dict[str, Any]]:
    with PooledConn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, tenant_id, name, identifier, description,
                   config_json, is_enabled, created_by, created_at, updated_at
            FROM rbac.mcp_servers
            WHERE id = %s
            """,
            (server_id,),
        )
        cols = [d[0] for d in cur.description]
        row = cur.fetchone()
        return dict(zip(cols, row)) if row else None


def create(
    tenant_id: str,
    name: str,
    identifier: str,
    description: str,
    config_json: Dict[str, Any],
    created_by: str,
) -> Dict[str, Any]:
    config_str = json.dumps(config_json, ensure_ascii=False)
    with PooledConn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO rbac.mcp_servers
                (tenant_id, name, identifier, description, config_json, created_by)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, tenant_id, name, identifier, description,
                      config_json, is_enabled, created_by, created_at, updated_at
            """,
            (tenant_id, name, identifier, description, config_str, created_by),
        )
        cols = [d[0] for d in cur.description]
        row = cur.fetchone()
        conn.commit()
        return dict(zip(cols, row))


def update(
    server_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    config_json: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    fields = []
    params = []
    if name is not None:
        fields.append("name = %s")
        params.append(name)
    if description is not None:
        fields.append("description = %s")
        params.append(description)
    if config_json is not None:
        fields.append("config_json = %s")
        params.append(json.dumps(config_json, ensure_ascii=False))
    if not fields:
        return get_by_id(server_id)
    fields.append("updated_at = now()")
    params.append(server_id)

    sql = f"""
        UPDATE rbac.mcp_servers
        SET {', '.join(fields)}
        WHERE id = %s
        RETURNING id, tenant_id, name, identifier, description,
                  config_json, is_enabled, created_by, created_at, updated_at
    """
    with PooledConn() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description]
        row = cur.fetchone()
        conn.commit()
        return dict(zip(cols, row)) if row else None


def set_enabled(server_id: str, enabled: bool) -> None:
    with PooledConn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE rbac.mcp_servers SET is_enabled=%s, updated_at=now() WHERE id=%s",
            (enabled, server_id),
        )
        conn.commit()


def delete(server_id: str) -> bool:
    with PooledConn() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM rbac.mcp_servers WHERE id=%s RETURNING id",
            (server_id,),
        )
        row = cur.fetchone()
        conn.commit()
        return row is not None


def upsert_tools(
    server_id: str,
    tools: List[Dict[str, Any]],
) -> None:
    """
    Sync tools for a server: delete removed ones, insert new ones, keep existing.
    tools: list of {tool_name, description, input_schema}
    """
    with PooledConn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT tool_name FROM rbac.mcp_tools WHERE server_id=%s",
            (server_id,),
        )
        existing = {r[0] for r in cur.fetchall()}

        incoming = {t["tool_name"] for t in tools}

        # Delete tools not in incoming
        if existing - incoming:
            cur.execute(
                "DELETE FROM rbac.mcp_tools WHERE server_id=%s AND tool_name = ANY(%s::text[])",
                (server_id, list(existing - incoming)),
            )

        # Insert new tools
        for t in tools:
            tool_name = t["tool_name"]
            desc = t.get("description", "")
            schema = json.dumps(t.get("input_schema", {}), ensure_ascii=False)
            cur.execute(
                """
                INSERT INTO rbac.mcp_tools
                    (server_id, tool_name, description, input_schema)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (server_id, tool_name)
                DO UPDATE SET description = EXCLUDED.description,
                              input_schema = EXCLUDED.input_schema
                """,
                (server_id, tool_name, desc, schema),
            )
        conn.commit()


def list_tools_by_server(server_id: str) -> List[Dict[str, Any]]:
    with PooledConn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, server_id, tool_name, description, input_schema, is_enabled, created_at
            FROM rbac.mcp_tools
            WHERE server_id = %s
            ORDER BY tool_name
            """,
            (server_id,),
        )
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        return [dict(zip(cols, r)) for r in rows]


def get_tool_by_id(tool_id: str) -> Optional[Dict[str, Any]]:
    with PooledConn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, server_id, tool_name, description, input_schema, is_enabled, created_at
            FROM rbac.mcp_tools
            WHERE id = %s
            """,
            (tool_id,),
        )
        cols = [d[0] for d in cur.description]
        row = cur.fetchone()
        return dict(zip(cols, row)) if row else None


def set_tool_enabled(tool_id: str, enabled: bool) -> None:
    with PooledConn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE rbac.mcp_tools SET is_enabled=%s WHERE id=%s",
            (enabled, tool_id),
        )
        conn.commit()
