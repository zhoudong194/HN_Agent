"""
recall.py — Multi-way召回引擎

三路召回 + RRF融合 + Cross-Encoder精排

召回策略：
  Route 1 (dense)  : pgvector HNSW — cosine similarity on BGE embeddings
  Route 2 (sparse) : BM25 — keyword match, language-aware Chinese tokenization
  Route 3 (exact)  : PostgreSQL LIKE — exact phrase match for high precision

Fusion         : Reciprocal Rank Fusion (RRF) with k=60
Reranker       : BAAI/bge-reranker-base — cross-encoder精排Top-N
Quality gates  : min_text_len, cjk_ratio, score floor
"""

from __future__ import annotations

import hashlib
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

import config
import database

# Lazy imports so the module loads even if models are not ready yet
_bm25_index: Optional["BM25Okapi"] = None
_bm25_corpus: List[Tuple[str, str]] = []   # (chunk_id, text)
_reranker: Optional[Any] = None


# ----------------------------------------------------------------------
# Quality gates
# ----------------------------------------------------------------------
MIN_TEXT_LEN = 30          # drop chunks shorter than this
MIN_CJK_RATIO = 0.15       # at least 15% Chinese characters
MIN_RETRIEVE_SCORE = 0.35  # cosine similarity floor (after RRF)
MIN_DENSE_SCORE = 0.45     # filter weak dense matches before fusion
MIN_DENSE_ONLY_SCORE = 0.55


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
    text = re.sub(r"[\u3000-\u303f\uff00-\uffef]", " ", text)   # fullwidth → space
    return text.lower().strip()


# ----------------------------------------------------------------------
# BM25 index management
# ----------------------------------------------------------------------
def build_bm25_index() -> None:
    """
    构建/重建 BM25 内存索引。
    从 PostgreSQL 读取所有有效 chunk，用 jieba 分词（中文） / split（英文）。
    """
    global _bm25_index, _bm25_corpus

    try:
        import jieba
    except ImportError:
        import sys, logging
        logging.getLogger(__name__).warning("jieba not installed, using simple split for BM25")
        jieba = None

    import logging
    log = logging.getLogger(__name__)
    log.info("Building BM25 index from PostgreSQL...")

    with database._PooledConn() as conn:
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
        # 标题作为前缀上下文
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


# ----------------------------------------------------------------------
# BM25 search
# ----------------------------------------------------------------------
def bm25_search(query: str, top_k: int = 20) -> List[Tuple[str, float]]:
    """
    BM25 keyword search.

    Returns list of (chunk_id, bm25_score), sorted descending.
    """
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


# ----------------------------------------------------------------------
# Dense search (pgvector)
# ----------------------------------------------------------------------
def dense_search(query_vector: List[float], top_k: int = 20) -> List[Tuple[str, float]]:
    """
    pgvector HNSW cosine similarity search.

    Returns list of (chunk_id, cosine_similarity), sorted descending.
    """
    results = database.search_similar_chunks(
        query_vector=query_vector,
        top_k=top_k,
        min_score=MIN_DENSE_SCORE,
    )
    return [(r["id"], r["score"]) for r in results]


# ----------------------------------------------------------------------
# Exact phrase search (PostgreSQL LIKE)
# ----------------------------------------------------------------------
def exact_search(query: str, top_k: int = 5) -> List[Tuple[str, float]]:
    """
    PostgreSQL LIKE 精确短语匹配 — 兜底高频关键词不命中问题。
    提取 query 中 ≥2 个字符的中文词/英文词做 AND 匹配。
    """
    terms = re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z0-9]{2,}", query)
    if not terms:
        return []

    with database._PooledConn() as conn:
        cur = conn.cursor()
        # 构建 AND 条件
        conditions = " AND ".join(["text ILIKE %s"] * len(terms))
        params = [f"%{t}%" for t in terms]
        sql = f"""
            SELECT c.id, c.text,
                   COUNT(*) FILTER (WHERE text ILIKE %(t)s) AS match_count
            FROM chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE d.status = 'active' AND ({conditions})
            GROUP BY c.id, c.text
            ORDER BY match_count DESC, LENGTH(text)
            LIMIT %s
        """
        full_params = {f"t{i}": t for i, t in enumerate(terms)}
        full_params["t"] = terms
        params.append(top_k)
        cur.execute(
            f"SELECT c.id, c.text FROM chunks c "
            f"JOIN documents d ON d.id = c.document_id "
            f"WHERE d.status='active' AND ({conditions}) "
            f"ORDER BY LENGTH(text) LIMIT %s",
            params,
        )
        cols = [d[0] for d in cur.description]
        results = []
        for row in cur.fetchall():
            r = dict(zip(cols, row))
            results.append((r["id"], 1.0))   # exact match = perfect score
        return results


# ----------------------------------------------------------------------
# RRF Fusion
# ----------------------------------------------------------------------
def rrf_fuse(
    dense_results: List[Tuple[str, float]],
    sparse_results: List[Tuple[str, float]],
    exact_results: List[Tuple[str, float]],
    k: int = 60,
    dense_weight: float = 1.0,
    sparse_weight: float = 1.0,
    exact_weight: float = 2.0,
) -> List[Tuple[str, float]]:
    """
    Reciprocal Rank Fusion combining multiple retrieval streams.

    exact_match gets extra weight since it's high precision.
    """
    scores: Dict[str, float] = {}

    for rank, (cid, score) in enumerate(dense_results):
        scores[cid] = scores.get(cid, 0) + dense_weight * (1 / (k + rank + 1))

    for rank, (cid, score) in enumerate(sparse_results):
        scores[cid] = scores.get(cid, 0) + sparse_weight * (1 / (k + rank + 1))

    for rank, (cid, score) in enumerate(exact_results):
        scores[cid] = scores.get(cid, 0) + exact_weight * (1 / (k + rank + 1))

    sorted_chunks = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return sorted_chunks


# ----------------------------------------------------------------------
# Cross-Encoder Reranker
# ----------------------------------------------------------------------
def _get_reranker():
    """Lazy-load the bge-reranker model from local dir or HF Hub.

    加载顺序：本地权重 → HF Hub。
    如果两者都失败，抛错（让 rerank() 走降级路径）。
    """
    global _reranker
    if _reranker is not None:
        return _reranker

    import logging
    log = logging.getLogger(__name__)

    # Try local directory first
    local_path = r"D:\Acode\HN_Agent\models\bge-reranker-base"
    pytorch_file = Path(local_path) / "pytorch_model.bin"
    onnx_dir = Path(local_path) / "onnx"
    onnx_file = onnx_dir / "model.onnx"

    # Check local weights
    has_pytorch = pytorch_file.exists() and pytorch_file.stat().st_size > 10_000_000
    has_onnx = False
    if onnx_file.exists():
        try:
            has_onnx = onnx_file.stat().st_size > 10_000_000
        except OSError:
            pass

    if has_pytorch or has_onnx:
        if has_onnx:
            log.info("Loading bge-reranker-base from local ONNX...")
            try:
                from sentence_transformers import CrossEncoder
                _reranker = CrossEncoder(str(onnx_file))
                log.info("Reranker loaded from ONNX")
                return _reranker
            except Exception as e:
                log.warning("ONNX load failed: %s", e)

        if has_pytorch:
            log.info("Loading bge-reranker-base from local PyTorch...")
            try:
                from sentence_transformers import CrossEncoder
                _reranker = CrossEncoder(
                    local_path,
                    max_length=512,
                )
                log.info("Reranker loaded from local PyTorch")
                return _reranker
            except Exception as e:
                log.warning("Local PyTorch load failed: %s", e)
    else:
        log.warning(
            "Reranker weights not found locally at %s "
            "(pytorch_model.bin/onnx missing). Skipping reranker.",
            local_path,
        )

    # No reranker available — set a flag so we don't retry
    _reranker = False
    return None


def rerank(query: str, chunk_ids: List[str], top_n: int = 5) -> List[Dict[str, Any]]:
    """
    Cross-encoder rerank via BAAI/bge-reranker-base.
    If the model is not available (download failed), falls back to returning
    the fusion result as-is (no-op reranking).
    """
    if not chunk_ids:
        return []

    # Load chunk texts
    placeholders = ",".join(["%s"] * len(chunk_ids))
    with database._PooledConn() as conn:
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

    # Try cross-encoder reranking; fall back to fusion order on failure
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
        # Reranker not available — return fusion order with neutral score
        import logging
        logging.getLogger(__name__).warning("Reranker unavailable, using fusion order")
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


# ----------------------------------------------------------------------
# Main multi-way retrieval
# ----------------------------------------------------------------------
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
    三路召回 → RRF融合 → Cross-Encoder精排 → 返回 Top-K

    Parameters
    ----------
    query       : 用户原始问题
    query_vector: BGE embedding 向量
    top_k       : 最终返回条数
    retrieve_k  : 每路召回条数（融合候选集更大=更好的多样性）
    min_score   : reranker 之后的最低分门槛
    """
    t0 = time.time()

    # 1. 三路召回并行
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

    # 2. RRF 融合
    fused = rrf_fuse(dense_hits, sparse_hits, exact_hits, k=60)
    fused_ids = [cid for cid, _ in fused]
    fused_score_map = {cid: score for cid, score in fused}

    # 3. Cross-Encoder 精排
    final = rerank(query, fused_ids, top_n=max(top_k * 2, 10))

    for item in final:
        cid = item.get("id")
        if cid in fused_score_map:
            item["rrf_score"] = fused_score_map[cid]

    # 4. 质量门：min_score 过滤
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


# ----------------------------------------------------------------------
# Standalone reindex (call after ingestion / cleanup)
# ----------------------------------------------------------------------
def rebuild_bm25():
    """重建 BM25 索引（入库/删除后调用）。"""
    global _bm25_index, _bm25_corpus
    _bm25_index = None
    _bm25_corpus = []
    build_bm25_index()
