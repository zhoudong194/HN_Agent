"""
biz_rag/query/schema.py — Query-related Pydantic schemas.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


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
