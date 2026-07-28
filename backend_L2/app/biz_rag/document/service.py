"""
biz_rag/document/service.py — Document business logic.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from biz_rag.document.repository import (
    archive_document as repo_archive,
    create_document as repo_create_document,
    find_document as repo_find_document,
    get_categories as repo_get_categories,
    get_chunk_count as repo_get_chunk_count,
    get_document_chunk_count,
    hard_delete_document as repo_hard_delete,
    insert_chunks_batch,
    list_documents as repo_list_documents,
)

log = logging.getLogger(__name__)


class DocumentNotFoundError(Exception):
    """Raised when document is not found."""


class DuplicateDocumentError(Exception):
    """Raised when document content hash already exists."""


class DocumentIngestionError(Exception):
    """Raised when document ingestion fails."""


def create_new_document(
    filename: str,
    file_type: str,
    file_size: int,
    content: bytes,
    category: Optional[str] = None,
    uploader: Optional[str] = None,
) -> dict:
    """Create document record. Raises DuplicateDocumentError if hash exists."""
    doc, is_new = repo_create_document(
        filename=filename,
        file_type=file_type,
        file_size=file_size,
        content=content,
        category=category,
        uploader=uploader,
        title=filename.rsplit(".", 1)[0] if filename else None,
    )
    if not is_new:
        raise DuplicateDocumentError("duplicate document")
    return doc


def get_document(doc_id: str) -> dict:
    """Get document by ID. Raises DocumentNotFoundError if not found."""
    doc = repo_find_document(doc_id)
    if doc is None:
        raise DocumentNotFoundError("document not found")
    return doc


def list_documents(
    status: Optional[str] = "active",
    category: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[dict]:
    """List documents with optional filters."""
    return repo_list_documents(status=status, category=category, limit=limit, offset=offset)


def archive_doc(doc_id: str) -> None:
    """Soft delete a document. Raises DocumentNotFoundError if not found."""
    ok = repo_archive(doc_id)
    if not ok:
        raise DocumentNotFoundError("document not found")


def hard_delete_doc(doc_id: str) -> None:
    """Permanently delete a document. Raises DocumentNotFoundError if not found."""
    doc = repo_find_document(doc_id)
    if doc is None:
        raise DocumentNotFoundError("document not found")
    repo_hard_delete(doc_id)


def ingest_chunks(doc_id: str, chunk_records: List[dict]) -> int:
    """Ingest chunk records for a document. Returns count inserted."""
    n = insert_chunks_batch(chunk_records)
    log.info("Inserted %d chunks for document %s", n, doc_id)
    return n


def get_total_chunk_count() -> int:
    """Get total active chunk count."""
    return repo_get_chunk_count()


def get_documents_categories() -> List[str]:
    """Get distinct active categories."""
    return repo_get_categories()


def build_document_info(doc: dict) -> dict:
    """Build document info with chunk count."""
    chunk_cnt = get_document_chunk_count(doc["id"])
    return {
        "id": str(doc["id"]),
        "filename": doc["filename"],
        "file_type": doc["file_type"],
        "file_size": doc["file_size"],
        "category": doc.get("category"),
        "uploader": doc.get("uploader"),
        "title": doc.get("title"),
        "status": doc["status"],
        "version": doc["version"],
        "uploaded_at": doc["uploaded_at"],
        "updated_at": doc["updated_at"],
        "chunk_count": chunk_cnt,
    }
