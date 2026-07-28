"""
biz_rag/document/api.py — Document management API.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form

from base_framework.base.security import CurrentUser
from biz_auth.deps import require_permission
from biz_rag.document.service import (
    DocumentIngestionError,
    DocumentNotFoundError,
    DuplicateDocumentError,
    archive_doc,
    build_document_info,
    create_new_document,
    get_documents_categories,
    get_total_chunk_count,
    hard_delete_doc,
    ingest_chunks,
    list_documents,
)
from biz_rag.document.schema import (
    CategoryResponse,
    DocumentInfo,
    IngestResponse,
)

log = logging.getLogger(__name__)
router = APIRouter()

# Data directory for file storage
DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)


@router.post("/documents", response_model=IngestResponse)
async def upload_document(
    file: UploadFile = File(...),
    category: Optional[str] = Form(None),
    uploader: Optional[str] = Form(None),
    _user: CurrentUser = Depends(require_permission("doc:write")),
):
    """Upload and ingest a document (.docx / .md)."""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".docx", ".doc", ".md"}:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {suffix}. Supported: .docx, .doc, .md",
        )

    target = DATA_DIR / file.filename
    target.parent.mkdir(parents=True, exist_ok=True)
    content = await file.read()
    with open(target, "wb") as f:
        f.write(content)
    log.info("Saved upload: %s (%d bytes)", target, len(content))

    try:
        doc = create_new_document(
            filename=file.filename,
            file_type=suffix,
            file_size=len(content),
            content=content,
            category=category,
            uploader=uploader,
        )
    except DuplicateDocumentError:
        raise HTTPException(
            status_code=409,
            detail=f"文件 '{file.filename}' 已存在且内容相同（SHA-256 重复检测）。如需重新入库，请先删除旧记录。",
        )

    doc_id = doc["id"]

    try:
        from data_ingestion import convert_to_markdown, create_semantic_chunks, setup_embedding_model

        documents = convert_to_markdown(str(target))
        if not documents:
            raise DocumentIngestionError("无法从文件中提取文本")

        nodes = create_semantic_chunks(documents)
        embed_model = setup_embedding_model()

        chunk_records = []
        for i, node in enumerate(nodes):
            text = node.get_text()
            if not text or len(text.strip()) < 10:
                continue
            vec = embed_model.get_text_embedding(text)
            chunk_records.append({
                "document_id": doc_id,
                "text": text,
                "vec": vec,
                "header_1": node.metadata.get("header_1"),
                "header_2": node.metadata.get("header_2"),
                "header_3": node.metadata.get("header_3"),
                "source_file": str(target),
                "chunk_index": i,
            })

        if chunk_records:
            ingest_chunks(doc_id, chunk_records)
            log.info("Inserted %d chunks for %s", len(chunk_records), file.filename)

        total = get_total_chunk_count()

        return IngestResponse(
            id=str(doc_id),
            filename=file.filename,
            chunks_added=len(chunk_records),
            total_chunks=total,
            message=f"已成功入库 '{file.filename}'（{len(chunk_records)} 个语义块）",
        )

    except DocumentIngestionError:
        hard_delete_doc(doc_id)
        raise HTTPException(status_code=500, detail="入库失败")


@router.get("/documents", response_model=List[DocumentInfo])
async def list_all_documents(
    status: Optional[str] = Query(None, description="active / archived / 空=全部"),
    category: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    _user: CurrentUser = Depends(require_permission("policy:read")),
):
    docs = list_documents(status=status, category=category, limit=limit, offset=offset)
    return [DocumentInfo(**build_document_info(doc)) for doc in docs]


@router.delete("/documents/{doc_id}", response_model=dict)
async def archive_document(
    doc_id: str,
    _user: CurrentUser = Depends(require_permission("doc:write")),
):
    """Soft delete a document (mark as archived)."""
    try:
        archive_doc(doc_id)
    except DocumentNotFoundError:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"message": f"Document {doc_id} has been archived.", "status": "archived"}


@router.delete("/documents/{doc_id}/hard", response_model=dict)
async def permanently_delete_document(
    doc_id: str,
    _user: CurrentUser = Depends(require_permission("doc:write")),
):
    """Permanently delete a document and all its chunks."""
    try:
        hard_delete_doc(doc_id)
    except DocumentNotFoundError:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"message": f"Document {doc_id} permanently deleted.", "status": "deleted"}


@router.get("/categories", response_model=CategoryResponse)
async def list_categories(
    _user: CurrentUser = Depends(require_permission("policy:read")),
):
    """Return all distinct active document categories."""
    cats = get_documents_categories()
    return CategoryResponse(categories=cats)
