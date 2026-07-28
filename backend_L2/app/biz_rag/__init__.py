"""
biz_rag/__init__.py — Biz RAG domain entry point.
Exports api_router for automatic discovery by main.py.
"""

from fastapi import APIRouter

from biz_rag.document.api import router as document_router
from biz_rag.query.api import router as query_router

api_router = APIRouter()
api_router.include_router(document_router)
api_router.include_router(query_router)

__all__ = ["api_router"]
