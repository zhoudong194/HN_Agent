"""
biz_mcp/server/model.py — SQLAlchemy-free row helpers for mcp_servers table.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from uuid import UUID


def row_to_server_row(row: tuple) -> Dict[str, Any]:
    cols = [
        "id", "tenant_id", "name", "identifier", "description",
        "config_json", "is_enabled", "created_by", "created_at", "updated_at",
    ]
    return dict(zip(cols, row))


def server_row_to_dict(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    return {
        "id": str(row["id"]),
        "tenant_id": str(row["tenant_id"]),
        "name": row["name"],
        "identifier": row["identifier"],
        "description": row["description"] or "",
        "config_json": row["config_json"] or {},
        "is_enabled": row["is_enabled"],
        "created_by": str(row["created_by"]) if row.get("created_by") else None,
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }
