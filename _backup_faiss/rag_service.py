"""
rag_service.py - Reusable RAG service using FAISS + SQLite.

v3 重大变化：
  • FAISS IndexHNSWFlat 替代 ChromaDB/pgvector，向量搜索完全本地化
  • SQLite 替代 PostgreSQL，元数据存储无需额外部署
  • cosine similarity via normalized vectors + inner product
"""

from __future__ import annotations

import io
import logging
import sys
from typing import Any, Dict, List, Optional

import config
import database

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# LLM client
# ----------------------------------------------------------------------
class _QwenClient:
    """Thin wrapper around OpenAI SDK compatible with 阿里云通义千问."""

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ):
        from openai import OpenAI

        self.model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._client = OpenAI(api_key=api_key, base_url=base_url)

    def complete(self, prompt: str) -> str:
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        )
        return resp.choices[0].message.content or ""


SYSTEM_PROMPT = """你是一个企业规章制度咨询助手，基于阿里云通义千问（qwen-plus）模型提供智能问答服务。请根据以下检索到的内容，准确回答用户的问题。

回答要求：
1. 只基于提供的内容进行回答，不要编造信息
2. 如果检索到的内容中没有相关信息，请明确告知用户
3. 回答要清晰、专业，引用相关条款
4. 使用中文回答
5. 如果用户问你是哪个模型、用了什么AI系统、或类似元问题，直接回答："我是阿里云通义千问（qwen-plus）语言模型"

检索到的内容：
{context}

用户问题：{query}

回答："""


class PolicyRAGService:
    """RAG 服务核心类（单例模式）。使用 FAISS + SQLite 进行向量检索。"""

    def __init__(self):
        self.embed_model = None
        self._llm_client = None
        self._has_api_key = False
        self._initialized = False

    def initialize(self) -> Dict[str, Any]:
        if self._initialized:
            return self._status()

        logger.info("Initializing PolicyRAGService v3 (FAISS + SQLite)")

        # Embedding model
        print("[RAG] Loading BGE embedding model...")
        from llama_index.embeddings.huggingface import HuggingFaceEmbedding

        self.embed_model = HuggingFaceEmbedding(
            model_name=config.EMBED_MODEL_NAME,
            query_instruction="为这个句子生成表示以用于检索相关文章：",
            text_instruction="把这段文章转化成一个向量表示：",
            embed_batch_size=32,
        )
        print(f"[RAG] Embedding model: {config.EMBED_MODEL_NAME} (dim={config.EMBED_DIM})")

        # LLM
        print("[RAG] Configuring LLM...")
        api_key = config.OPENAI_API_KEY
        api_base = config.OPENAI_API_BASE
        self._has_api_key = bool(api_key and api_key.strip())

        if not self._has_api_key:
            print("[RAG] OPENAI_API_KEY not set -> retrieval-only mode")
        else:
            print(f"[RAG] LLM: {config.LLM_MODEL} ({api_base})")
            self._llm_client = _QwenClient(
                model=config.LLM_MODEL,
                api_key=api_key,
                base_url=api_base,
                temperature=config.LLM_TEMPERATURE,
                max_tokens=config.LLM_MAX_TOKENS,
            )

        self._initialized = True
        print("[RAG] PolicyRAGService initialized")
        return self._status()

    def _status(self) -> Dict[str, Any]:
        try:
            chunk_count = database.get_chunk_count()
            docs = database.list_documents(status="active")
            doc_count = len(docs)
        except Exception as e:
            logger.warning("Failed to get status: %s", e)
            chunk_count = 0
            doc_count = 0

        return {
            "initialized": self._initialized,
            "llm_available": self._has_api_key,
            "embedding_model": config.EMBED_MODEL_NAME,
            "llm_model": config.LLM_MODEL if self._has_api_key else "none",
            "vector_store": "FAISS IndexHNSW",
            "metadata_store": "SQLite",
            "document_count": doc_count,
            "chunk_count": chunk_count,
        }

    def get_status(self) -> Dict[str, Any]:
        if not self._initialized:
            try:
                self.initialize()
            except Exception as e:
                return {"initialized": False, "error": str(e)}
        return self._status()

    def query(
        self,
        user_question: str,
        top_k: Optional[int] = None,
        min_score: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        RAG 查询主入口。

        步骤：
          1. BGE 将用户问题转为向量
          2. FAISS HNSW 找到最相似的 chunk
          3. LLM 生成答案（或仅返回检索结果）
        """
        if not self._initialized:
            self.initialize()

        k = top_k or config.TOP_K
        threshold = min_score if min_score is not None else config.SIMILARITY_THRESHOLD

        result: Dict[str, Any] = {
            "query": user_question,
            "mode": "llm" if self._has_api_key else "retrieval_only",
            "answer": "",
            "sources": [],
        }

        # Step 1: 计算查询向量
        query_vector = self.embed_model.get_query_embedding(user_question)

        # Step 2: FAISS 检索
        hits = database.search_similar_chunks(
            query_vector=query_vector,
            top_k=k,
            min_score=threshold,
        )

        result["sources"] = hits

        if not hits:
            result["answer"] = "未找到相关内容，请尝试换一种问法。"
            return result

        # Step 3: LLM 生成
        context_blocks = [hit["text"] for hit in hits]
        context = "\n\n---\n\n".join(context_blocks)

        if self._has_api_key and self._llm_client:
            prompt = SYSTEM_PROMPT.format(context=context, query=user_question)
            try:
                answer = self._llm_client.complete(prompt)
                result["answer"] = answer
            except Exception as e:
                logger.exception("LLM call failed")
                result["answer"] = f"查询失败: {e}"
        else:
            result["answer"] = (
                "当前使用直接检索模式（未配置 OPENAI_API_KEY），"
                "以上为检索到的原文摘录。如需获得 LLM 智能回答，请配置 API Key。\n\n"
                f"检索结果：\n{context}"
            )
            result["mode"] = "retrieval_only"

        return result


# ----------------------------------------------------------------------
# Module-level singleton
# ----------------------------------------------------------------------
_service: Optional[PolicyRAGService] = None


def get_service() -> PolicyRAGService:
    global _service
    if _service is None:
        _service = PolicyRAGService()
    return _service


def query_policy(user_question: str) -> str:
    """CLI 兼容函数。"""
    svc = get_service()
    return svc.query(user_question).get("answer", "")


def initialize_rag():
    svc = get_service()
    svc.initialize()
    return svc


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    initialize_rag()
    out = get_service().query("网络原理实验指导书的内容有哪些？")
    print("\n=== ANSWER ===")
    print(out["answer"])
    print(f"\n=== SOURCES: {len(out['sources'])} chunks, mode={out['mode']} ===")
    for i, src in enumerate(out["sources"], 1):
        print(f"\n[{i}] score={src['score']} | {src.get('header_1', '')} / {src.get('header_2', '')}")
        print(src["text"][:200])
