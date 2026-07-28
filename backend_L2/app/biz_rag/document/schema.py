"""
biz_rag/document/schema.py — Document-related Pydantic schemas.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class DocumentInfo(BaseModel):
    id: str
    filename: str
    file_type: str
    file_size: int
    category: Optional[str] = None
    uploader: Optional[str] = None
    title: Optional[str] = None
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
