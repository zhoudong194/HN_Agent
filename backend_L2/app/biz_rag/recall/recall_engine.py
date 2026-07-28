"""
biz_rag/recall/recall_engine.py — Multi-way recall engine.

Three-way retrieval + RRF fusion + Cross-Encoder reranking.

Recall routes:
  Route 1 (dense)  : pgvector HNSW — cosine similarity on BGE embeddings
  Route 2 (sparse) : BM25 — keyword match, language-aware Chinese tokenization
  Route 3 (exact)  : PostgreSQL LIKE — exact phrase match for high precision

Fusion         : Reciprocal Rank Fusion (RRF) with k=60
Reranker       : BAAI/bge-reranker-base — cross-encoder reranking Top-N
Quality gates  : min_text_len, cjk_ratio, score floor
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from base_framework.base.config import (
    EMBED_DIM,
    SIMILARITY_THRESHOLD,
    TOP_K,
)
from biz_rag.document.repository import get_chunk_count, list_documents

log = logging.getLogger(__name__)

# Quality gates
MIN_TEXT_LEN = 30
MIN_CJK_RATIO = 0.15
MIN_RETRIEVE_SCORE = 0.35
MIN_DENSE_SCORE = 0.45
MIN_DENSE_ONLY_SCORE = 0.55

# Lazy-loaded models
_bm25_index: Optional["BM25Okapi"] = None
_bm25_corpus: List[Tuple[str, str]] = []
_reranker: Optional[Any] = None


def _quality_pass(text: str) -> bool:
    """Return True if chunk passes content quality gates."""
    if len(text.strip()) < MIN_TEXT_LEN:
        return False
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    if cjk / max(len(text), 1) < MIN_CJK_RATIO:
        return False
    return True


def _normalize_for_bm25(text: str) -> str:
    """Light Chinese normalization for BM25 tokenization."""
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"[\u3000-\u303f\uff00-\uffef]", " ", text)
    return text.lower().strip()


def build_bm25_index() -> None:
    """Build/rebuild BM25 in-memory index from PostgreSQL."""
    global _bm25_index, _bm25_corpus

    try:
        import jieba
    except ImportError:
        log.warning("jieba not installed, using simple split for BM25")
        jieba = None

    log.info("Building BM25 index from PostgreSQL...")

    from base_framework.base.db_engine import PooledConn
    with PooledConn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT c.id, c.text, c.document_id, c.header_1, c.header_2,
                   c.header_3, c.source_file, c.chunk_index,
                   d.filename, d.category
            FROM chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE d.status = 'active' AND c.embedding IS NOT NULL
        """)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]

    _bm25_corpus = []
    corpus_texts = []

    for r in rows:
        text = r["text"]
        if not _quality_pass(text):
            continue
        header = ""
        for h in [r.get("header_1"), r.get("header_2"), r.get("header_3")]:
            if h:
                header += h + " "
        full_text = (header + text).strip()

        chunk_id = r["id"]
        _bm25_corpus.append((chunk_id, full_text))

        if jieba:
            tokens = list(jieba.cut(_normalize_for_bm25(full_text)))
        else:
            tokens = _normalize_for_bm25(full_text).split()
        corpus_texts.append(tokens)

    from rank_bm25 import BM25Okapi
    _bm25_index = BM25Okapi(corpus_texts)
    log.info(f"BM25 index built: {len(_bm25_corpus)} chunks")


def ensure_bm25() -> None:
    """Lazily build BM25 if not yet built."""
    if _bm25_index is None:
        build_bm25_index()


def bm25_search(query: str, top_k: int = 20) -> List[Tuple[str, float]]:
    """BM25 keyword search. Returns list of (chunk_id, bm25_score)."""
    ensure_bm25()

    try:
        import jieba
        tokens = list(jieba.cut(_normalize_for_bm25(query)))
    except ImportError:
        tokens = _normalize_for_bm25(query).split()

    scores = _bm25_index.get_scores(tokens)
    top_indices = np.argsort(scores)[::-1]

    results = []
    for idx in top_indices:
        score = float(scores[idx])
        if score <= 0:
            break
        sid, _ = _bm25_corpus[idx]
        results.append((sid, score))
        if len(results) >= top_k:
            break
    return results


def dense_search(query_vector: List[float], top_k: int = 20) -> List[Tuple[str, float]]:
    """pgvector HNSW cosine similarity search. Returns list of (chunk_id, cosine_similarity)."""
    from biz_rag.document.repository import search_similar_chunks

    results = search_similar_chunks(
        query_vector=query_vector,
        top_k=top_k,
        min_score=MIN_DENSE_SCORE,
    )
    return [(r["id"], r["score"]) for r in results]


def exact_search(query: str, top_k: int = 5) -> List[Tuple[str, float]]:
    """PostgreSQL LIKE exact phrase match for high precision."""
    terms = re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z0-9]{2,}", query)
    if not terms:
        return []

    from base_framework.base.db_engine import PooledConn
    with PooledConn() as conn:
        cur = conn.cursor()
        conditions = " AND ".join(["text ILIKE %s"] * len(terms))
        params = [f"%{t}%" for t in terms]
        params.append(top_k)
        cur.execute(
            f"SELECT c.id, c.text FROM chunks c "
            f"JOIN documents d ON d.id = c.document_id "
            f"WHERE d.status='active' AND ({conditions}) "
            f"ORDER BY LENGTH(text) LIMIT %s",
            params,
        )
        cols = [d[0] for d in cur.description]
        return [(dict(zip(cols, row))["id"], 1.0) for row in cur.fetchall()]


def rrf_fuse(
    dense_results: List[Tuple[str, float]],
    sparse_results: List[Tuple[str, float]],
    exact_results: List[Tuple[str, float]],
    k: int = 60,
    dense_weight: float = 1.0,
    sparse_weight: float = 1.0,
    exact_weight: float = 2.0,
) -> List[Tuple[str, float]]:
    """Reciprocal Rank Fusion combining multiple retrieval streams."""
    scores: Dict[str, float] = {}

    for rank, (cid, _) in enumerate(dense_results):
        scores[cid] = scores.get(cid, 0) + dense_weight * (1 / (k + rank + 1))
    for rank, (cid, _) in enumerate(sparse_results):
        scores[cid] = scores.get(cid, 0) + sparse_weight * (1 / (k + rank + 1))
    for rank, (cid, _) in enumerate(exact_results):
        scores[cid] = scores.get(cid, 0) + exact_weight * (1 / (k + rank + 1))

    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


def _get_reranker():
    """Lazy-load the bge-reranker model from local dir or HF Hub."""
    global _reranker
    if _reranker is not None:
        return _reranker if _reranker is not False else None

    # Try local directory first
    local_path = r"D:\Acode\HN_Agent\models\bge-reranker-base"
    pytorch_file = Path(local_path) / "pytorch_model.bin"
    onnx_dir = Path(local_path) / "onnx"
    onnx_file = onnx_dir / "model.onnx"

    has_pytorch = pytorch_file.exists() and pytorch_file.stat().st_size > 10_000_000
    has_onnx = False
    if onnx_file.exists():
        try:
            has_onnx = onnx_file.stat().st_size > 10_000_000
        except OSError:
            pass

    if has_pytorch or has_onnx:
        try:
            from sentence_transformers import CrossEncoder
            if has_onnx:
                log.info("Loading bge-reranker-base from local ONNX...")
                _reranker = CrossEncoder(str(onnx_file))
            else:
                log.info("Loading bge-reranker-base from local PyTorch...")
                _reranker = CrossEncoder(local_path, max_length=512)
            return _reranker
        except Exception as e:
            log.warning("Reranker load failed: %s", e)

    _reranker = False
    return None


def rerank(query: str, chunk_ids: List[str], top_n: int = 5) -> List[Dict[str, Any]]:
    """Cross-encoder rerank via BAAI/bge-reranker-base."""
    if not chunk_ids:
        return []

    from base_framework.base.db_engine import PooledConn
    placeholders = ",".join(["%s"] * len(chunk_ids))
    with PooledConn() as conn:
        cur = conn.cursor()
        cur.execute(f"""
            SELECT c.id, c.text, c.document_id, c.header_1, c.header_2,
                   c.header_3, c.source_file, c.chunk_index,
                   d.filename, d.category
            FROM chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE c.id IN ({placeholders})
        """, list(chunk_ids))
        cols = [d[0] for d in cur.description]
        chunk_map = {r["id"]: r for r in (dict(zip(cols, row)) for row in cur.fetchall())}

    pairs = []
    valid_ids = []
    for cid in chunk_ids:
        if cid not in chunk_map:
            continue
        r = chunk_map[cid]
        header = " ".join(filter(None, [r.get("header_1") or "", r.get("header_2") or ""]))
        full_text = (header + " " + r["text"]).strip()
        pairs.append([query, full_text])
        valid_ids.append(cid)

    if not pairs:
        return []

    try:
        reranker = _get_reranker()
        if reranker is None:
            raise RuntimeError("Reranker not available")
        cross_scores = reranker.predict(pairs, show_progress_bar=False)
        reranked = []
        for cid, cs in zip(valid_ids, cross_scores):
            r = chunk_map[cid]
            reranked.append({
                "id": cid,
                "text": r["text"],
                "document_id": r["document_id"],
                "header_1": r.get("header_1"),
                "header_2": r.get("header_2"),
                "header_3": r.get("header_3"),
                "source_file": r.get("source_file"),
                "chunk_index": r.get("chunk_index"),
                "doc_filename": r.get("filename"),
                "doc_category": r.get("category"),
                "score": float(cs),
                "rrf_score": r.get("rrf_score"),
            })
        reranked.sort(key=lambda x: x["score"], reverse=True)
        return reranked[:top_n]
    except Exception:
        log.warning("Reranker unavailable, using fusion order")
        results = []
        for rank, cid in enumerate(chunk_ids[:top_n]):
            if cid not in chunk_map:
                continue
            r = chunk_map[cid]
            results.append({
                "id": cid,
                "text": r["text"],
                "document_id": r["document_id"],
                "header_1": r.get("header_1"),
                "header_2": r.get("header_2"),
                "header_3": r.get("header_3"),
                "source_file": r.get("source_file"),
                "chunk_index": r.get("chunk_index"),
                "doc_filename": r.get("filename"),
                "doc_category": r.get("category"),
                "score": None,
                "rrf_score": r.get("rrf_score"),
            })
        return results


@dataclass
class RetrievalResult:
    sources: List[Dict[str, Any]]
    retrieval_stats: Dict[str, Any] = field(default_factory=dict)


def multi_way_retrieve(
    query: str,
    query_vector: List[float],
    top_k: int = 5,
    retrieve_k: int = 20,
    min_score: float = MIN_RETRIEVE_SCORE,
) -> RetrievalResult:
    """
    Three-way recall -> RRF fusion -> Cross-Encoder reranking -> Top-K
    """
    t0 = time.time()

    dense_hits = dense_search(query_vector, top_k=retrieve_k)
    sparse_hits = bm25_search(query, top_k=retrieve_k)
    exact_hits = exact_search(query, top_k=5)

    dense_ids = {cid for cid, _ in dense_hits}
    sparse_ids = {cid for cid, _ in sparse_hits}

    if dense_hits and not sparse_hits and not exact_hits and dense_hits[0][1] < MIN_DENSE_ONLY_SCORE:
        return RetrievalResult(
            sources=[],
            retrieval_stats={
                "dense_count": len(dense_ids),
                "sparse_count": 0,
                "exact_count": 0,
                "fused_candidates": 0,
                "after_rerank": 0,
                "after_filter": 0,
                "rejected_reason": "dense_only_low_score",
                "latency_ms": round((time.time() - t0) * 1000, 1),
            },
        )

    fused = rrf_fuse(dense_hits, sparse_hits, exact_hits, k=60)
    fused_ids = [cid for cid, _ in fused]
    fused_score_map = {cid: score for cid, score in fused}

    final = rerank(query, fused_ids, top_n=max(top_k * 2, 10))

    for item in final:
        cid = item.get("id")
        if cid in fused_score_map:
            item["rrf_score"] = fused_score_map[cid]

    filtered = []
    for r in final:
        score = r.get("score")
        fallback_score = r.get("rrf_score")
        effective_score = score if score is not None else fallback_score
        if effective_score is None:
            continue
        if effective_score >= min_score:
            filtered.append(r)
        if len(filtered) >= top_k:
            break

    stats = {
        "dense_count": len(dense_ids),
        "sparse_count": len(sparse_ids),
        "exact_count": len(exact_hits),
        "fused_candidates": len(fused),
        "after_rerank": len(final),
        "after_filter": len(filtered),
        "latency_ms": round((time.time() - t0) * 1000, 1),
    }

    return RetrievalResult(sources=filtered, retrieval_stats=stats)


def rebuild_bm25() -> None:
    """Rebuild BM25 index after ingestion/cleanup."""
    global _bm25_index, _bm25_corpus
    _bm25_index = None
    _bm25_corpus = []
    build_bm25_index()
