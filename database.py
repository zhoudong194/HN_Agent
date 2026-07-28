"""
database.py — PostgreSQL + pgvector as the primary store.

All data (vectors + metadata) lives in a single PostgreSQL database served
by the pgvector Docker container on localhost:5433.

Schema
======
  documents  — source file metadata (mirrors the old SQLite schema)
  chunks     — text chunks + 1024-dim BGE embeddings (vector type)

Indexes
=======
  chunks_embedding_idx — HNSW index on embedding (cosine distance)
  idx_chunks_document_id / idx_documents_status — btree auxiliary lookups
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import bcrypt
import psycopg2
from psycopg2 import pool
from psycopg2.extras import execute_values

import config

# Default admin password, rewritten as a real bcrypt hash on first boot.
_DEFAULT_ADMIN_EMAIL = "admin@example.com"
_DEFAULT_ADMIN_PASSWORD = "admin123"

# ----------------------------------------------------------------------
# Connection pool
# ----------------------------------------------------------------------
_APP_DIR = Path(__file__).resolve().parent

_pg_pool: Optional[pool.ThreadedConnectionPool] = None


def _get_pg_pool() -> pool.ThreadedConnectionPool:
    global _pg_pool
    if _pg_pool is None:
        _pg_pool = pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=10,
            host=config.DB_HOST,
            port=config.DB_PORT,
            dbname=config.DB_NAME,
            user=config.DB_USER,
            password=config.DB_PASSWORD,
        )
    return _pg_pool


def _conn():
    """Get a connection from the pool. Auto-closed back to pool on __exit__."""
    return _get_pg_pool().getconn()


class _PooledConn:
    """Context manager that returns a connection to the pool on exit."""

    def __init__(self):
        self._conn = None

    def __enter__(self):
        self._conn = _conn()
        return self._conn

    def __exit__(self, *args):
        if self._conn:
            _get_pg_pool().putconn(self._conn)


def _row_to_dict(cur) -> Dict[str, Any]:
    """Convert a psycopg2 cursor result row to dict using column names."""
    cols = [d[0] for d in cur.description]
    row = cur.fetchone()
    return dict(zip(cols, row)) if row else None


def _rows_to_dicts(cur) -> List[Dict[str, Any]]:
    """Convert all rows from a psycopg2 cursor to list of dicts."""
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]
def create_document(
    filename: str,
    file_type: str,
    file_size: int,
    content: Optional[bytes] = None,
    category: Optional[str] = None,
    uploader: Optional[str] = None,
    title: Optional[str] = None,
) -> Tuple[Dict[str, Any], bool]:
    """
    创建文档记录。检测 SHA-256 哈希避免重复入库。

    返回 (doc_dict, is_new):
      is_new=True  → 新插入
      is_new=False → 检测到哈希冲突，返回已有记录
    """
    file_hash = hashlib.sha256(content).hexdigest() if content else None
    doc_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    with _PooledConn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM documents WHERE file_hash=%s AND status='active'",
            (file_hash,),
        )
        existing = cur.fetchone()
        if existing:
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, existing)), False

        cur.execute("""
            INSERT INTO documents
                (id, filename, file_type, file_size, file_hash,
                 category, uploader, title, status, version, uploaded_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'active', 1, %s, %s)
        """, (doc_id, filename, file_type, file_size, file_hash,
              category, uploader, title, now, now))
        conn.commit()

        cur.execute("SELECT * FROM documents WHERE id=%s", (doc_id,))
        cols = [d[0] for d in cur.description]
        row = cur.fetchone()
        return dict(zip(cols, row)), True


def get_document(doc_id: str) -> Optional[Dict[str, Any]]:
    with _PooledConn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM documents WHERE id=%s", (doc_id,))
        cols = [d[0] for d in cur.description]
        row = cur.fetchone()
        return dict(zip(cols, row)) if row else None


def list_documents(
    status: Optional[str] = "active",
    category: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    clauses, params = [], []
    if status:
        clauses.append("status=%s")
        params.append(status)
    if category:
        clauses.append("category=%s")
        params.append(category)

    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    query = f"SELECT * FROM documents{where} ORDER BY uploaded_at DESC LIMIT %s OFFSET %s"
    params += [limit, offset]

    with _PooledConn() as conn:
        cur = conn.cursor()
        cur.execute(query, params)
        return _rows_to_dicts(cur)


def archive_document(doc_id: str) -> bool:
    with _PooledConn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE documents SET status='archived', updated_at=%s WHERE id=%s AND status='active'",
            (datetime.now(timezone.utc).isoformat(), doc_id),
        )
        conn.commit()
        return cur.rowcount > 0


def hard_delete_document(doc_id: str) -> bool:
    with _PooledConn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM chunks WHERE document_id=%s", (doc_id,))
        cur.execute("DELETE FROM documents WHERE id=%s", (doc_id,))
        conn.commit()
        return True


def insert_chunk(
    chunk_id: str,
    document_id: str,
    text: str,
    vec: List[float],
    header_1: Optional[str] = None,
    header_2: Optional[str] = None,
    header_3: Optional[str] = None,
    source_file: Optional[str] = None,
    chunk_index: int = 0,
) -> bool:
    text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    vec_str = "[" + ",".join(str(v) for v in vec) + "]"

    with _PooledConn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM chunks WHERE text_hash=%s AND document_id=%s",
            (text_hash, document_id),
        )
        if cur.fetchone():
            return False

        cur.execute("""
            INSERT INTO chunks
                (id, document_id, text, text_hash, header_1, header_2, header_3,
                 source_file, chunk_index, embedding)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector)
        """, (chunk_id, document_id, text, text_hash,
              header_1, header_2, header_3, source_file, chunk_index, vec_str))
        conn.commit()
        return True


def insert_chunks_batch(chunks: List[Dict[str, Any]]) -> int:
    """
    Bulk-insert chunks using execute_values for performance.
    Each chunk dict must contain: document_id, text, vec, header_1/2/3, source_file, chunk_index
    """
    if not chunks:
        return 0

    rows = []
    for c in chunks:
        chunk_id = c.get("id", str(uuid.uuid4()))
        text_hash = hashlib.sha256(c["text"].encode("utf-8")).hexdigest()
        vec_str = "[" + ",".join(str(v) for v in c["vec"]) + "]"
        rows.append((
            chunk_id,
            c["document_id"],
            c["text"],
            text_hash,
            c.get("header_1"),
            c.get("header_2"),
            c.get("header_3"),
            c.get("source_file"),
            c.get("chunk_index", 0),
            vec_str,
        ))

    with _PooledConn() as conn:
        cur = conn.cursor()
        execute_values(
            cur,
            """
            INSERT INTO chunks
                (id, document_id, text, text_hash, header_1, header_2, header_3,
                 source_file, chunk_index, embedding)
            VALUES %s
            ON CONFLICT (id) DO NOTHING
            """,
            rows,
            template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector)",
        )
        conn.commit()
        return cur.rowcount


def search_similar_chunks(
    query_vector: List[float],
    top_k: int = 5,
    min_score: float = 0.0,
    document_id: Optional[str] = None,
    exclude_chunk_ids: Optional[List[str]] = None,
) -> List[dict]:
    """
    pgvector cosine similarity search via HNSW index.

    Parameters
    ----------
    query_vector : 1024-dim BGE embedding
    top_k        : number of results to return
    min_score    : minimum cosine similarity (0–1), 0 = no filter
    document_id  : optional, restrict to a single document
    exclude_chunk_ids : optional, exclude specific chunk IDs

    Returns
    -------
    List[dict] with id / text / score / metadata
    """
    vec_str = "[" + ",".join(str(v) for v in query_vector) + "]"

    clauses = ["1=1"]
    params: List[Any] = [vec_str]

    if document_id:
        clauses.append("c.document_id = %s")
        params.append(document_id)
    if exclude_chunk_ids:
        clauses.append("c.id != ALL(%s)")
        params.append(exclude_chunk_ids)

    where = " AND ".join(clauses)
    query = f"""
        SELECT
            c.id,
            c.text,
            c.document_id,
            c.header_1,
            c.header_2,
            c.header_3,
            c.source_file,
            c.chunk_index,
            d.filename  AS doc_filename,
            d.category  AS doc_category,
            1 - (c.embedding <=> %s::vector) AS score
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE {where}
          AND d.status = 'active'
          AND c.embedding IS NOT NULL
        ORDER BY c.embedding <=> %s::vector
        LIMIT %s
    """
    # Note: <=> is cosine distance; 1 - distance = cosine similarity
    params += [vec_str, top_k]

    with _PooledConn() as conn:
        cur = conn.cursor()
        cur.execute(query, params)
        rows = _rows_to_dicts(cur)

    results = []
    for row in rows:
        score = float(row["score"])
        if min_score > 0 and score < min_score:
            continue
        results.append({
            "id": row["id"],
            "text": row["text"],
            "document_id": row["document_id"],
            "header_1": row["header_1"],
            "header_2": row["header_2"],
            "header_3": row["header_3"],
            "source_file": row["source_file"],
            "chunk_index": row["chunk_index"],
            "doc_filename": row["doc_filename"],
            "doc_category": row["doc_category"],
            "score": round(score, 4),
        })
    return results


def get_chunk_count() -> int:
    with _PooledConn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE d.status = 'active'
        """)
        return cur.fetchone()[0]


def get_document_chunk_count(doc_id: str) -> int:
    with _PooledConn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM chunks WHERE document_id=%s",
            (doc_id,),
        )
        return cur.fetchone()[0]


def get_categories() -> List[str]:
    with _PooledConn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT DISTINCT category FROM documents
            WHERE status='active' AND category IS NOT NULL AND category != ''
        """)
        return [r[0] for r in cur.fetchall()]


def rebuild_index():
    """pgvector maintains the HNSW index automatically on INSERT.
    This is a no-op kept for API compatibility with the old FAISS pipeline."""
    pass


def init_tables():
    """Table creation is handled by the Docker init script.
    Called on import to verify connectivity."""
    try:
        with _PooledConn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1")
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("init_tables: %s", e)


# ----------------------------------------------------------------------
# RBAC schema bootstrap
# ----------------------------------------------------------------------
_RBAC_SQL_PATH = _APP_DIR / "_rbac_init.sql"


def _hash_password(plain: str) -> str:
    """bcrypt hash in modular crypt format. Truncate to 72 bytes (bcrypt limit)."""
    pw = plain.encode("utf-8")[:72]
    return bcrypt.hashpw(pw, bcrypt.gensalt(rounds=10)).decode("ascii")


def ensure_rbac_schema() -> None:
    """
    Apply _rbac_init.sql if the rbac schema is missing, then refresh the
    placeholder admin password with a real bcrypt hash. Idempotent.
    """
    log = logging.getLogger(__name__)
    sql_text = _RBAC_SQL_PATH.read_text(encoding="utf-8")

    with _PooledConn() as conn:
        cur = conn.cursor()
        cur.execute(sql_text)
        conn.commit()

        # Rewrite placeholder hash for the seeded admin user
        admin_pw_hash = _hash_password(_DEFAULT_ADMIN_PASSWORD)
        cur.execute(
            "UPDATE rbac.users SET pw_hash=%s "
            "WHERE email=%s AND pw_hash='__SEED__PLACEHOLDER__'",
            (admin_pw_hash, _DEFAULT_ADMIN_EMAIL),
        )
        if cur.rowcount:
            log.info("[RBAC] Seeded admin user password (email=%s)", _DEFAULT_ADMIN_EMAIL)
        conn.commit()
