"""
biz_rag/query/api.py — RAG query API.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from base_framework.base.security import CurrentUser
from biz_auth.deps import require_permission
from biz_rag.query.schema import QueryRequest, QueryResponse, SourceItem
from biz_rag.query.service import get_rag_service, reset_rag_service

log = logging.getLogger(__name__)
router = APIRouter()


@router.post("/query", response_model=QueryResponse)
async def query(
    req: QueryRequest,
    _user: CurrentUser = Depends(require_permission("policy:read")),
):
    svc = get_rag_service()
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
