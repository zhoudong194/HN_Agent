"""
base_framework/base/db_engine.py — PostgreSQL + pgvector connection pool.

Provides:
  - Connection pool management
  - PooledConn context manager
  - Row-to-dict helpers
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import psycopg2
from psycopg2 import pool
from psycopg2.extras import execute_values

from base_framework.base.config import (
    DB_HOST,
    DB_PORT,
    DB_NAME,
    DB_USER,
    DB_PASSWORD,
)

log = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Connection pool
# ----------------------------------------------------------------------
_pg_pool: Optional[pool.ThreadedConnectionPool] = None


def _get_pg_pool() -> pool.ThreadedConnectionPool:
    global _pg_pool
    if _pg_pool is None:
        _pg_pool = pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=10,
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
        )
    return _pg_pool


def _conn():
    """Get a connection from the pool. Auto-closed back to pool on __exit__."""
    return _get_pg_pool().getconn()


class PooledConn:
    """Context manager that returns a connection to the pool on exit."""

    def __enter__(self):
        self._conn = _conn()
        return self._conn

    def __exit__(self, *args):
        if self._conn:
            _get_pg_pool().putconn(self._conn)


def row_to_dict(cur) -> Optional[Dict[str, Any]]:
    """Convert first row of psycopg2 cursor to dict using column names."""
    cols = [d[0] for d in cur.description]
    row = cur.fetchone()
    return dict(zip(cols, row)) if row else None


def rows_to_dicts(cur) -> List[Dict[str, Any]]:
    """Convert all rows from a psycopg2 cursor to list of dicts."""
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def verify_connectivity() -> bool:
    """Verify database connectivity. Called on startup."""
    try:
        with PooledConn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1")
        return True
    except Exception as e:
        log.warning("Database connectivity check failed: %s", e)
        return False
