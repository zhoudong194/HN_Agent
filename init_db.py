"""
init_db.py - initialize PostgreSQL + pgvector schema.

This script is intentionally small and idempotent. It is used by Docker
startup and can also be run locally:

    python init_db.py

It creates:
  - public.documents
  - public.chunks with embedding vector(1024)
  - pgvector / pgcrypto extensions
  - RBAC schema and seed admin user, when _rbac_init.sql is present
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import database

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

APP_DIR = Path(__file__).resolve().parent
SCHEMA_SQL = APP_DIR / "schema.sql"


def init_database() -> None:
    if not SCHEMA_SQL.exists():
        raise FileNotFoundError(f"Missing schema file: {SCHEMA_SQL}")

    print("[1/3] Applying public schema...")
    schema_sql = SCHEMA_SQL.read_text(encoding="utf-8")
    with database._PooledConn() as conn:
        cur = conn.cursor()
        cur.execute(schema_sql)
        conn.commit()
    print("  OK: documents / chunks / pgvector are ready")

    print("[2/3] Applying RBAC schema...")
    try:
        database.ensure_rbac_schema()
        print("  OK: RBAC schema is ready")
    except FileNotFoundError:
        print("  SKIP: _rbac_init.sql not found")

    print("[3/3] Verifying tables...")
    with database._PooledConn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_schema IN ('public', 'rbac')
            ORDER BY table_schema, table_name
            """
        )
        for schema, table in cur.fetchall():
            print(f"  - {schema}.{table}")

    print("\n[OK] Database initialization complete.")


if __name__ == "__main__":
    init_database()
