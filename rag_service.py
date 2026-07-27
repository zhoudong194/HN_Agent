"""
rag_service.py - Reusable RAG service module for the web backend.
This is the core layer used by server.py (FastAPI).

Compared to rag_query.py, the public API is redesigned to return structured
data (dict) instead of just a string, so the FastAPI layer can serialize it
easily.

All runtime configuration (API keys, model names, paths) is loaded via
`config.py`, which reads from .env + process environment.
"""

import os
import sys
import io
import logging
from typing import Optional, Dict, List, Any

import config

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Custom OpenAI-compatible client — bypasses llama_index's LLM layer entirely.
# LlamaIndex's built-in OpenAI class uses /v1/completions — 阿里云 rejects this.
# This class uses /v1/chat/completions directly via the OpenAI SDK.
# ----------------------------------------------------------------------
class _QwenClient:
    """
    Thin wrapper around the OpenAI SDK compatible with 阿里云通义千问.
    Routes all generation requests through /v1/chat/completions.
    """

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

# LlamaIndex core
from llama_index.core import VectorStoreIndex
from llama_index.core.retrievers import VectorIndexRetriever

# ChromaDB vector store
import chromadb
from llama_index.vector_stores.chroma import ChromaVectorStore

# Embedding model
from llama_index.embeddings.huggingface import HuggingFaceEmbedding

# Configuration (re-exported for backward compatibility with data_ingestion/server.py)
CHROMA_PERSIST_DIR = config.CHROMA_PERSIST_DIR
COLLECTION_NAME = config.COLLECTION_NAME

# Embedding model config
EMBED_MODEL_NAME = config.EMBED_MODEL_NAME
EMBED_DIM = config.EMBED_DIM

# LLM Configuration (OpenAI-compatible API)
LLM_MODEL = config.LLM_MODEL
LLM_TEMPERATURE = config.LLM_TEMPERATURE
LLM_MAX_TOKENS = config.LLM_MAX_TOKENS

# RAG retrieval config
TOP_K = config.TOP_K


SYSTEM_PROMPT = """你是一个企业规章制度咨询助手，基于阿里云通义千问（qwen-plus）模型提供智能问答服务。请根据以下检索到的规章制度内容，准确回答用户的问题。

回答要求：
1. 只基于提供的规章制度内容进行回答，不要编造信息
2. 如果检索到的内容中没有相关信息，请明确告知用户
3. 回答要清晰、专业，引用相关条款
4. 使用中文回答
5. 如果用户问你是哪个模型、用了什么AI系统、或类似元问题，直接回答："我是阿里云通义千问（qwen-plus）语言模型"，不需要检索内容即可回答

检索到的规章制度内容：
{context}

用户问题：{query}

回答："""


class PolicyRAGService:
    """Reusable RAG service. Singleton-style, used by the FastAPI layer."""

    def __init__(self):
        self.embed_model = None
        self.index = None
        self._llm_client = None
        self._initialized = False
        self._has_api_key = False

    def initialize(self) -> Dict[str, Any]:
        """Initialize embedding model, LLM, and vector store."""
        if self._initialized:
            return self._status()

        logger.info("Initializing PolicyRAGService")
        print("[RAG] Loading BGE embedding model...")
        self.embed_model = HuggingFaceEmbedding(
            model_name=EMBED_MODEL_NAME,
            query_instruction="为这个句子生成表示以用于检索相关文章：",
            text_instruction="把这段文章转化成一个向量表示：",
            embed_batch_size=32,
        )

        print("[RAG] Configuring LLM...")
        api_key = config.OPENAI_API_KEY
        api_base = config.OPENAI_API_BASE
        self._has_api_key = bool(api_key and api_key.strip())

        if not self._has_api_key:
            print("[RAG] OPENAI_API_KEY not set -> retrieval-only mode")
        else:
            print(f"[RAG] Using 阿里云通义千问 model: {config.LLM_MODEL}")

        # _QwenClient: thin wrapper around OpenAI /v1/chat/completions.
        # Completely bypasses LlamaIndex's LLM layer (which uses /v1/completions).
        self._llm_client = (
            _QwenClient(
                model=config.LLM_MODEL,
                api_key=api_key,
                base_url=api_base or "https://api.openai.com/v1",
                temperature=config.LLM_TEMPERATURE,
                max_tokens=config.LLM_MAX_TOKENS,
            )
            if self._has_api_key
            else None
        )

        print("[RAG] Connecting to ChromaDB vector store...")
        chroma_client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
        collection = chroma_client.get_collection(name=COLLECTION_NAME)

        vector_store = ChromaVectorStore(chroma_collection=collection)
        self.index = VectorStoreIndex.from_vector_store(
            vector_store=vector_store,
            embed_model=self.embed_model,
        )

        self._initialized = True
        print("[RAG] PolicyRAGService initialized")
        return self._status()

    def _status(self) -> Dict[str, Any]:
        count = 0
        if self._initialized:
            try:
                client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
                count = client.get_collection(name=COLLECTION_NAME).count()
            except Exception:
                count = 0
        return {
            "initialized": self._initialized,
            "llm_available": self._has_api_key,
            "embedding_model": EMBED_MODEL_NAME,
            "llm_model": config.LLM_MODEL if self._has_api_key else "none",
            "collection": COLLECTION_NAME,
            "document_count": count,
        }

    def get_status(self) -> Dict[str, Any]:
        """Public status snapshot for /api/health."""
        if not self._initialized:
            try:
                self.initialize()
            except Exception as e:
                return {"initialized": False, "error": str(e)}
        return self._status()

    def query(self, user_question: str, top_k: Optional[int] = None) -> Dict[str, Any]:
        """
        Run a RAG query: retrieve relevant chunks, then generate answer via
        阿里云通义千问 (bypassing LlamaIndex's LLM layer entirely).
        """
        if not self._initialized:
            self.initialize()

        k = top_k or TOP_K
        result: Dict[str, Any] = {
            "query": user_question,
            "mode": "llm" if self._has_api_key else "retrieval_only",
            "answer": "",
            "sources": [],
        }

        # 1. Retrieve relevant chunks
        retriever = VectorIndexRetriever(
            index=self.index,
            similarity_top_k=k,
        )
        nodes = retriever.retrieve(user_question)
        result["sources"] = self._format_sources(nodes)

        if not nodes:
            result["answer"] = "未找到相关规章制度内容，请尝试换一种问法。"
            return result

        # 2. Build context from chunks
        context_blocks = [node.get_text() for node in nodes]
        context = "\n\n---\n\n".join(context_blocks)

        # 3. Generate answer with LLM (or return raw context if no API key)
        if self._has_api_key and self._llm_client is not None:
            prompt = SYSTEM_PROMPT.format(context=context, query=user_question)
            try:
                answer = self._llm_client.complete(prompt)
                result["answer"] = answer
            except Exception as e:
                result["answer"] = f"查询失败: {e}"
        else:
            result["answer"] = (
                "当前使用直接检索模式（未配置 OPENAI_API_KEY），"
                "以上为检索到的原文摘录。如需获得 LLM 生成的智能回答，请配置 API Key。\n\n"
                f"检索结果：\n{context}"
            )
            result["mode"] = "retrieval_only"

        return result

    @staticmethod
    def _format_sources(nodes) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for node in nodes:
            score = getattr(node, "score", None)
            metadata = {}
            try:
                metadata = dict(node.node.metadata or {})
            except Exception:
                try:
                    metadata = dict(node.metadata or {})
                except Exception:
                    metadata = {}
            text = ""
            try:
                text = node.get_text()
            except Exception:
                text = str(getattr(node, "node", node))
            out.append({
                "text": text,
                "score": float(score) if score is not None else None,
                "metadata": metadata,
            })
        return out


# Module-level singleton
_service: Optional[PolicyRAGService] = None


def get_service() -> PolicyRAGService:
    """Get (and lazily create) the process-wide RAG service."""
    global _service
    if _service is None:
        _service = PolicyRAGService()
    return _service


# Backward-compatible function-style API used by the original CLI.
def query_policy(user_question: str) -> str:
    svc = get_service()
    result = svc.query(user_question)
    return result.get("answer", "")


def initialize_rag():
    return get_service().initialize()


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    initialize_rag()
    out = get_service().query("请问我有多少天年假？有什么请假制度？")
    print("\n=== ANSWER ===")
    print(out["answer"])
    print(f"\n=== SOURCES: {len(out['sources'])} chunks, mode={out['mode']} ===")
