"""
server.py - FastAPI backend for the Company Rules RAG system.

Exposes a small REST surface plus a single-page web UI (static/index.html).

Endpoints:
    GET  /                  -> static/index.html
    GET  /api/health        -> service status
    POST /api/query         -> RAG query
    POST /api/ingest        -> upload a .docx / .md file and ingest it
    GET  /api/documents     -> list ingested documents
    DELETE /api/documents   -> wipe the collection (rebuild)
"""

import io
import os
import sys
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import List

# Force UTF-8 stdout for predictable logging
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("server")

import config  # centralized .env-driven configuration

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# Project modules
from rag_service import get_service, CHROMA_PERSIST_DIR, COLLECTION_NAME
from data_ingestion import (
    DATA_DIR,
    setup_embedding_model,
    setup_vector_store,
    scan_data_directory,
    create_semantic_chunks,
    convert_to_markdown,
)

# Log effective (non-secret) config on startup so misconfiguration is visible
log.info("Loaded configuration: %s", config.status_summary())

# ----------------------------------------------------------------------
# App setup
# ----------------------------------------------------------------------

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
STATIC_DIR.mkdir(exist_ok=True)

app = FastAPI(
    title="Company Rules RAG API",
    version="1.0.0",
    description="RAG backend for company policy Q&A (LLM + retrieval-only fallback).",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve the single-page UI
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ----------------------------------------------------------------------
# Schemas
# ----------------------------------------------------------------------


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)


class SourceItem(BaseModel):
    text: str
    score: float | None = None
    metadata: dict = Field(default_factory=dict)


class QueryResponse(BaseModel):
    query: str
    mode: str  # "llm" | "retrieval_only"
    answer: str
    sources: List[SourceItem]


class HealthResponse(BaseModel):
    initialized: bool
    llm_available: bool
    embedding_model: str
    llm_model: str
    collection: str
    document_count: int


class IngestResponse(BaseModel):
    filename: str
    chunks_added: int
    total_chunks: int
    collection_size: int
    message: str


class DocumentInfo(BaseModel):
    filename: str
    file_type: str
    size_bytes: int
    modified_at: str


# ----------------------------------------------------------------------
# Routes
# ----------------------------------------------------------------------


@app.get("/", include_in_schema=False)
async def index():
    """Serve the single-page web UI."""
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="UI not built yet")
    return FileResponse(str(index_file))


@app.get("/api/health", response_model=HealthResponse)
async def health():
    """Service status snapshot."""
    svc = get_service()
    status = svc.get_status()
    if not status.get("initialized"):
        raise HTTPException(status_code=503, detail=svc.get_status())
    return HealthResponse(**status)


@app.post("/api/query", response_model=QueryResponse)
async def query(req: QueryRequest):
    """Run a RAG query against the knowledge base."""
    svc = get_service()
    try:
        result = svc.query(req.question, top_k=req.top_k)
    except Exception as e:
        log.exception("Query failed")
        raise HTTPException(status_code=500, detail=str(e))

    sources = [SourceItem(**s) for s in result.get("sources", [])]
    return QueryResponse(
        query=result["query"],
        mode=result["mode"],
        answer=result["answer"],
        sources=sources,
    )


@app.post("/api/ingest", response_model=IngestResponse)
async def ingest(file: UploadFile = File(...)):
    """Upload a single .docx / .md file and add it to the vector store."""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".docx", ".md"}:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {suffix}. Supported: .docx, .md",
        )

    target = Path(DATA_DIR) / file.filename
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "wb") as f:
        shutil.copyfileobj(file.file, f)
    log.info("Saved upload to %s", target)

    # Run the ingestion pipeline scoped to this one file
    documents = convert_to_markdown(str(target))
    if not documents:
        raise HTTPException(status_code=400, detail="Could not extract text from file")

    from llama_index.core import StorageContext, VectorStoreIndex
    parser_kwargs = dict(include_metadata=True, include_prev_next_rel=True)
    from llama_index.core.node_parser import MarkdownNodeParser
    from llama_index.core.schema import MetadataMode

    parser = MarkdownNodeParser(**parser_kwargs, metadata_mode=MetadataMode.ALL)
    nodes = parser.get_nodes_from_documents(documents)

    collection, _ = setup_vector_store()
    from llama_index.vector_stores.chroma import ChromaVectorStore

    vector_store = ChromaVectorStore(chroma_collection=collection)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)
    embed_model = setup_embedding_model()

    VectorStoreIndex(
        nodes=nodes,
        storage_context=storage_context,
        embed_model=embed_model,
        show_progress=False,
    )

    # Reset the RAG service so next request reloads the new vectors
    from rag_service import _service as svc_singleton
    svc_singleton._initialized = False

    collection_size = collection.count()
    return IngestResponse(
        filename=file.filename,
        chunks_added=len(nodes),
        total_chunks=len(nodes),
        collection_size=collection_size,
        message=f"Successfully ingested '{file.filename}' ({len(nodes)} chunks).",
    )


@app.get("/api/documents", response_model=List[DocumentInfo])
async def list_documents():
    """List files currently in the data directory."""
    docs: List[DocumentInfo] = []
    data_path = Path(DATA_DIR)
    if not data_path.exists():
        return docs
    for p in sorted(data_path.iterdir()):
        if p.is_file() and p.suffix.lower() in {".docx", ".md", ".pdf"}:
            stat = p.stat()
            docs.append(
                DocumentInfo(
                    filename=p.name,
                    file_type=p.suffix.lower().lstrip("."),
                    size_bytes=stat.st_size,
                    modified_at=datetime.fromtimestamp(stat.st_mtime).isoformat(),
                )
            )
    return docs


@app.delete("/api/documents", response_model=dict)
async def clear_documents():
    """Drop the Chroma collection (data files are kept)."""
    import chromadb
    client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
    try:
        client.delete_collection(name=COLLECTION_NAME)
    except Exception as e:
        log.warning("delete_collection: %s", e)
    from rag_service import _service as svc_singleton
    svc_singleton._initialized = False
    return {"message": "Collection cleared. Re-ingest documents to repopulate."}


# ----------------------------------------------------------------------
# Startup
# ----------------------------------------------------------------------


@app.on_event("startup")
async def _warmup():
    """Pre-load the RAG service so the first /api/query is fast."""
    log.info("Warming up RAG service...")
    try:
        svc = get_service()
        svc.initialize()
        log.info("RAG service ready: %s", svc.get_status())
    except Exception as e:
        log.warning("RAG warmup failed: %s", e)


if __name__ == "__main__":
    import uvicorn

    host = config.HOST
    port = config.PORT
    log.info("Starting server on http://%s:%d", host, port)
    uvicorn.run("server:app", host=host, port=port, reload=False)
