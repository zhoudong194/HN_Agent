"""
server.py - FastAPI backend for Company Rules RAG system (PostgreSQL + pgvector).

v4 endpoints:
    GET  /                   -> static/index.html
    GET  /api/health        -> service status
    POST /api/query         -> RAG query
    POST /api/documents     -> upload a .docx / .md file and ingest it
    GET  /api/documents     -> list documents (with metadata)
    DELETE /api/documents/{id}  -> archive document (soft delete)
    DELETE /api/documents/{id}/hard -> permanently delete document
    GET  /api/categories    -> list distinct categories
"""

from __future__ import annotations

import io
import logging
import logging.handlers
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Logging to file — avoids "I/O on closed file" when running in background
APP_DIR = Path(__file__).resolve().parent
_log_file = APP_DIR / "server.log"
_log_handler = logging.handlers.RotatingFileHandler(
    str(_log_file), maxBytes=5_000_000, backupCount=3, encoding="utf-8"
)
_log_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logging.basicConfig(level=logging.INFO, handlers=[_log_handler])
log = logging.getLogger("server")

import config

from fastapi import FastAPI, HTTPException, Query, UploadFile, File, Form, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# Project modules
from rag_service import get_service
import database
from data_ingestion import (
    DATA_DIR,
    setup_embedding_model,
    convert_to_markdown,
    create_semantic_chunks,
)

# RBAC
from rbac import require_permission, require_user
from rbac_routes import router as rbac_router

# ----------------------------------------------------------------------
# App setup
# ----------------------------------------------------------------------
APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
STATIC_DIR.mkdir(exist_ok=True)

app = FastAPI(
    title="Company Rules RAG API",
    version="3.0.0",
    description="RAG backend powered by FAISS + SQLite.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Mount RBAC routes (/api/auth/* and /api/admin/*)
app.include_router(rbac_router, prefix="/api")

log.info("Loaded configuration: %s", config.status_summary())


# ----------------------------------------------------------------------
# Schemas
# ----------------------------------------------------------------------


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)
    min_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class SourceItem(BaseModel):
    id: str
    text: str
    score: Optional[float] = None
    rrf_score: Optional[float] = None
    header_1: Optional[str] = None
    header_2: Optional[str] = None
    header_3: Optional[str] = None
    doc_filename: Optional[str] = None
    doc_category: Optional[str] = None
    document_id: Optional[str] = None


class QueryResponse(BaseModel):
    query: str
    mode: str
    answer: str
    sources: List[SourceItem]
    retrieval_required: bool = True
    retrieval_stats: Optional[Dict[str, Any]] = None


class HealthResponse(BaseModel):
    initialized: bool
    llm_available: bool
    embedding_model: str
    llm_model: str
    collection: str = "PostgreSQL + pgvector"
    vector_store: str
    metadata_store: str
    document_count: int
    chunk_count: int


class DocumentInfo(BaseModel):
    id: str
    filename: str
    file_type: str
    file_size: int
    size_bytes: Optional[int] = None
    category: Optional[str]
    uploader: Optional[str]
    title: Optional[str]
    status: str
    version: int
    uploaded_at: str
    updated_at: str
    chunk_count: int = 0


class IngestResponse(BaseModel):
    id: str
    filename: str
    chunks_added: int
    total_chunks: int
    message: str


class CategoryResponse(BaseModel):
    categories: List[str]


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _reset_rag_service():
    from rag_service import _service as svc

    if svc is not None:
        svc._initialized = False


# ----------------------------------------------------------------------
# Routes
# ----------------------------------------------------------------------


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/api/health", response_model=HealthResponse)
async def health():
    svc = get_service()
    status = svc.get_status()
    if not status.get("initialized"):
        raise HTTPException(status_code=503, detail=status)
    return HealthResponse(**status)


@app.post("/api/query", response_model=QueryResponse)
async def query(req: QueryRequest, _user=Depends(require_permission("policy:read"))):
    svc = get_service()
    try:
        result = svc.query(
            req.question,
            top_k=req.top_k,
            min_score=req.min_score,
        )
    except Exception as e:
        log.exception("Query failed")
        raise HTTPException(status_code=500, detail=str(e))

    sources = [SourceItem(**s) for s in result.get("sources", [])]
    return QueryResponse(
        query=result["query"],
        mode=result["mode"],
        answer=result["answer"],
        sources=sources,
        retrieval_required=result.get("retrieval_required", True),
        retrieval_stats=result.get("retrieval_stats"),
    )


@app.post("/api/documents", response_model=IngestResponse)
async def upload_document(
    file: UploadFile = File(...),
    category: Optional[str] = Form(None),
    uploader: Optional[str] = Form(None),
    _user=Depends(require_permission("doc:write")),
):
    """
    上传单个文档（.docx / .md），解析文本、切块、向量化后存入 FAISS + SQLite。
    自动检测重复文件（SHA-256 哈希）。
    """
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".docx", ".doc", ".md"}:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {suffix}. Supported: .docx, .doc, .md",
        )

    # 保存文件到 data/
    target = Path(DATA_DIR) / file.filename
    target.parent.mkdir(parents=True, exist_ok=True)
    content = await file.read()
    with open(target, "wb") as f:
        f.write(content)
    log.info("Saved upload: %s (%d bytes)", target, len(content))

    # 创建数据库记录
    doc_record, is_new = database.create_document(
        filename=file.filename,
        file_type=suffix,
        file_size=len(content),
        content=content,
        category=category,
        uploader=uploader,
        title=Path(file.filename).stem,
    )

    if not is_new:
        raise HTTPException(
            status_code=409,
            detail=f"文件 '{file.filename}' 已存在且内容相同（SHA-256 重复检测）。如需重新入库，请先删除旧记录。",
        )

    doc_id = doc_record["id"]

    # 切块 + 向量化
    try:
        documents = convert_to_markdown(str(target))
        if not documents:
            raise ValueError("无法从文件中提取文本")

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
            n = database.insert_chunks_batch(chunk_records)
            # Rebuild FAISS index
            database.rebuild_index()
            log.info("Inserted %d chunks for %s", n, file.filename)

        _reset_rag_service()
        total = database.get_chunk_count()

        return IngestResponse(
            id=str(doc_id),
            filename=file.filename,
            chunks_added=len(chunk_records),
            total_chunks=total,
            message=f"已成功入库 '{file.filename}'（{len(chunk_records)} 个语义块）",
        )

    except Exception as e:
        log.exception("Ingestion failed")
        # 回滚：删除文档记录
        database.hard_delete_document(doc_id)
        raise HTTPException(status_code=500, detail=f"入库失败: {e}")


@app.get("/api/documents", response_model=List[DocumentInfo])
async def list_all_documents(
    status: Optional[str] = Query(None, description="active / archived / 空=全部"),
    category: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    _user=Depends(require_permission("policy:read")),
):
    docs = database.list_documents(status=status, category=category, limit=limit, offset=offset)
    result: List[DocumentInfo] = []
    for doc in docs:
        chunk_cnt = database.get_document_chunk_count(doc["id"])
        result.append(
            DocumentInfo(
                id=str(doc["id"]),
                filename=doc["filename"],
                file_type=doc["file_type"],
                file_size=doc["file_size"],
                size_bytes=doc["file_size"],
                category=doc.get("category"),
                uploader=doc.get("uploader"),
                title=doc.get("title"),
                status=doc["status"],
                version=doc["version"],
                uploaded_at=doc["uploaded_at"],
                updated_at=doc["updated_at"],
                chunk_count=chunk_cnt,
            )
        )
    return result


@app.delete("/api/documents/{doc_id}", response_model=dict)
async def archive_doc(doc_id: str, _user=Depends(require_permission("doc:write"))):
    """软删除文档（标记为 archived），其所有 chunk 同步删除。"""
    ok = database.archive_document(doc_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Document not found")
    _reset_rag_service()
    return {"message": f"Document {doc_id} has been archived.", "status": "archived"}


@app.delete("/api/documents/{doc_id}/hard", response_model=dict)
async def hard_delete_doc(doc_id: str, _user=Depends(require_permission("doc:write"))):
    """永久删除文档及全部 chunk（不可恢复）。"""
    doc = database.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    ok = database.hard_delete_document(doc_id)
    _reset_rag_service()
    return {"message": f"Document {doc_id} permanently deleted.", "status": "deleted"}


@app.get("/api/categories", response_model=CategoryResponse)
async def list_categories(_user=Depends(require_permission("policy:read"))):
    """返回所有已使用的文档分类（去重）。"""
    cats = database.get_categories()
    return CategoryResponse(categories=cats)


# ----------------------------------------------------------------------
# Startup
# ----------------------------------------------------------------------


@app.on_event("startup")
async def _warmup():
    log.info("Warming up RAG service...")
    try:
        database.ensure_rbac_schema()
        log.info("RBAC schema ensured")
    except Exception as e:
        log.exception("RBAC schema bootstrap failed: %s", e)
        raise
    try:
        svc = get_service()
        svc.initialize()
        log.info("RAG service ready: %s", svc.get_status())
    except Exception as e:
        log.warning("RAG warmup failed: %s — will retry on first request", e)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server:app", host=config.HOST, port=config.PORT, reload=False)
