"""
biz_rag/document/repository.py — Document data access layer.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from base_framework.base.db_engine import PooledConn


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
    Create a document record. Detects SHA-256 hash to avoid duplicate insertion.
    Returns (doc_dict, is_new):
      is_new=True  -> newly inserted
      is_new=False -> detected hash collision, returns existing record
    """
    file_hash = hashlib.sha256(content).hexdigest() if content else None
    doc_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    with PooledConn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, filename, file_type, file_size, file_hash, category, "
            "uploader, title, status, version, uploaded_at, updated_at "
            "FROM documents WHERE file_hash=%s AND status='active'",
            (file_hash,),
        )
        existing = cur.fetchone()
        if existing:
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, existing)), False

        cur.execute(
            """
            INSERT INTO documents
                (id, filename, file_type, file_size, file_hash,
                 category, uploader, title, status, version, uploaded_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'active', 1, %s, %s)
            """,
            (doc_id, filename, file_type, file_size, file_hash,
             category, uploader, title, now, now),
        )
        conn.commit()

        cur.execute(
            "SELECT id, filename, file_type, file_size, file_hash, category, "
            "uploader, title, status, version, uploaded_at, updated_at "
            "FROM documents WHERE id=%s",
            (doc_id,),
        )
        cols = [d[0] for d in cur.description]
        row = cur.fetchone()
        return dict(zip(cols, row)), True


def find_document(doc_id: str) -> Optional[Dict[str, Any]]:
    """Find a document by ID."""
    with PooledConn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, filename, file_type, file_size, category, "
            "uploader, title, status, version, uploaded_at, updated_at "
            "FROM documents WHERE id=%s",
            (doc_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))


def list_documents(
    status: Optional[str] = "active",
    category: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """List documents with optional filters."""
    clauses, params = [], []
    if status:
        clauses.append("status=%s")
        params.append(status)
    if category:
        clauses.append("category=%s")
        params.append(category)

    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    query = (
        f"SELECT id, filename, file_type, file_size, category, "
        f"uploader, title, status, version, uploaded_at, updated_at "
        f"FROM documents{where} ORDER BY uploaded_at DESC LIMIT %s OFFSET %s"
    )
    params.extend([limit, offset])

    with PooledConn() as conn:
        cur = conn.cursor()
        cur.execute(query, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def archive_document(doc_id: str) -> bool:
    """Soft delete a document (mark as archived)."""
    with PooledConn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE documents SET status='archived', updated_at=%s "
            "WHERE id=%s AND status='active'",
            (datetime.now(timezone.utc).isoformat(), doc_id),
        )
        conn.commit()
        return cur.rowcount > 0


def hard_delete_document(doc_id: str) -> bool:
    """Permanently delete a document and all its chunks."""
    with PooledConn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM chunks WHERE document_id=%s", (doc_id,))
        cur.execute("DELETE FROM documents WHERE id=%s", (doc_id,))
        conn.commit()
        return True


def insert_chunks_batch(chunks: List[Dict[str, Any]]) -> int:
    """
    Bulk-insert chunks using execute_values for performance.
    Each chunk dict must contain: document_id, text, vec, header_1/2/3, source_file, chunk_index
    """
    if not chunks:
        return 0

    from psycopg2.extras import execute_values

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

    with PooledConn() as conn:
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


def get_chunk_count() -> int:
    """Get total active chunk count."""
    with PooledConn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM chunks c "
            "JOIN documents d ON d.id = c.document_id "
            "WHERE d.status = 'active'"
        )
        return cur.fetchone()[0]


def get_document_chunk_count(doc_id: str) -> int:
    """Get chunk count for a specific document."""
    with PooledConn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM chunks WHERE document_id=%s",
            (doc_id,),
        )
        return cur.fetchone()[0]


def get_categories() -> List[str]:
    """Get distinct active document categories."""
    with PooledConn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT category FROM documents "
            "WHERE status='active' AND category IS NOT NULL AND category != ''"
        )
        return [r[0] for r in cur.fetchall()]


def search_similar_chunks(
    query_vector: List[float],
    top_k: int = 5,
    min_score: float = 0.0,
    document_id: Optional[str] = None,
    exclude_chunk_ids: Optional[List[str]] = None,
) -> List[dict]:
    """
    pgvector cosine similarity search via HNSW index.
    Returns list of dict with id / text / score / metadata.
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
    params += [vec_str, top_k]

    with PooledConn() as conn:
        cur = conn.cursor()
        cur.execute(query, params)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]

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
