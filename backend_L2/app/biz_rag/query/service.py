"""
biz_rag/query/service.py — RAG query business logic.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from base_framework.base.config import (
    EMBED_MODEL_NAME,
    LLM_MODEL,
    LLM_MAX_TOKENS,
    LLM_TEMPERATURE,
    OPENAI_API_BASE,
    OPENAI_API_KEY,
    SIMILARITY_THRESHOLD,
    TOP_K,
)

log = logging.getLogger(__name__)

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

POLICY_KEYWORDS = {
    "制度", "规章", "条款", "流程", "标准", "规定", "办法", "规则",
    "年假", "请假", "假期", "休假", "病假", "事假", "调休", "加班",
    "考勤", "迟到", "早退", "旷工", "全勤",
    "工资", "薪酬", "福利", "社保", "五险", "一金", "餐补",
    "报销", "差旅", "住宿", "交通", "发票", "财务",
    "采购", "付款", "预付款", "供应商", "审批", "申请",
    "办公用品", "设备", "入职", "离职", "合同", "人力", "hr",
    "policy", "leave", "vacation", "reimbursement", "expense",
    "purchase", "procurement", "attendance", "overtime", "salary",
    "benefit", "approval", "invoice",
}

DOC_TYPE_KEYWORDS = {
    "文档", "文件", "资料", "材料", "论文", "报告", "指导书", "实验", "课程",
    "手册", "说明书", "内容", "知识库", "入库",
}

DOC_ACTION_KEYWORDS = {
    "总结", "概括", "归纳", "摘要", "提炼", "梳理", "介绍", "讲了什么",
    "主要内容", "大意", "要点", "summary", "summarize",
}

DOC_MATCH_STOPWORDS = {
    "总结", "概括", "归纳", "摘要", "提炼", "梳理", "介绍", "一下", "这个",
    "那个", "文档", "文件", "资料", "材料", "内容", "主要", "什么", "怎么",
}

GREETING_PATTERNS = {
    "hi", "hello", "hey", "你好", "您好", "早上好", "上午好",
    "中午好", "下午好", "晚上好", "在吗", "嗨", "哈喽",
}
THANKS_PATTERNS = {"谢谢", "感谢", "多谢", "thanks", "thank you", "再见", "拜拜", "bye"}
META_PATTERNS = {"你是谁", "你能做什么", "你可以做什么", "你会什么", "介绍一下你", "help", "帮助"}


def _normalize_query(text: str) -> str:
    _NORM = re.compile(r"[\s，。！？!?,.;;：:、~`\"'""'''（）()\[\]{}<>《》]+")
    return _NORM.sub("", text.lower())


def _doc_match_terms(text: str) -> List[str]:
    normalized = _normalize_query(text)
    terms = set(re.findall(r"[a-zA-Z0-9]{2,}", normalized))

    try:
        import jieba
        for token in jieba.cut(text):
            token = _normalize_query(token)
            if len(token) >= 2:
                terms.add(token)
    except Exception:
        pass

    cjk = "".join(re.findall(r"[\u4e00-\u9fff]", normalized))
    for size in (2, 3, 4):
        for i in range(max(len(cjk) - size + 1, 0)):
            terms.add(cjk[i:i + size])

    return [t for t in terms if t and t not in DOC_MATCH_STOPWORDS]


def _query_mentions_known_document(raw: str, normalized: str) -> bool:
    from biz_rag.document.repository import list_documents

    try:
        docs = list_documents(status="active", limit=200)
    except Exception:
        return False

    query_terms = _doc_match_terms(raw)
    if not query_terms:
        return False

    for doc in docs:
        doc_name = " ".join(
            filter(None, [doc.get("filename"), doc.get("title"), doc.get("category")])
        )
        doc_key = _normalize_query(doc_name)
        if not doc_key:
            continue

        if len(normalized) >= 3 and (normalized in doc_key or doc_key in normalized):
            return True

        strong_hits = 0
        for term in query_terms:
            if term in doc_key:
                if len(term) >= 3:
                    return True
                strong_hits += 1
        if strong_hits >= 2:
            return True

    return False


def _route_query(user_question: str) -> Optional[Dict[str, Any]]:
    """Handle non-knowledge-base intents before retrieval."""
    raw = user_question.strip()
    normalized = _normalize_query(raw)
    lowered = raw.lower().strip()

    if not normalized:
        return {
            "mode": "chat",
            "answer": "请描述一下你想咨询的公司制度问题，比如年假、考勤、报销或采购流程。",
            "route": "empty",
        }

    if normalized in GREETING_PATTERNS or lowered in GREETING_PATTERNS:
        return {
            "mode": "chat",
            "answer": "您好！请问有什么关于公司规章制度的问题需要咨询？",
            "route": "greeting",
        }

    if normalized in THANKS_PATTERNS or lowered in THANKS_PATTERNS:
        return {
            "mode": "chat",
            "answer": "不客气。有制度、流程、报销、考勤等问题时可以继续问我。",
            "route": "courtesy",
        }

    if normalized in META_PATTERNS or lowered in META_PATTERNS:
        return {
            "mode": "chat",
            "answer": "我是企业规章制度咨询助手，可以根据已入库的制度文档回答年假、考勤、报销、采购、审批流程等问题，并给出相关引用来源。",
            "route": "meta",
        }

    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", raw))
    has_policy_keyword = any(k in lowered or k in raw for k in POLICY_KEYWORDS)
    has_doc_type_keyword = any(k in lowered or k in raw for k in DOC_TYPE_KEYWORDS)
    mentions_known_doc = _query_mentions_known_document(raw, normalized)
    should_retrieve = has_policy_keyword or has_doc_type_keyword or mentions_known_doc
    alnum_count = len(re.findall(r"[a-zA-Z0-9]", raw))

    if cjk_count == 0 and not should_retrieve:
        return {
            "mode": "chat",
            "answer": '请描述想咨询的制度或已入库文档问题，比如"年假有多少天""总结某篇论文"或"采购金额超过 5000 元怎么审批"。',
            "route": "non_knowledge_base",
        }

    if not should_retrieve:
        return {
            "mode": "chat",
            "answer": "请描述想咨询的制度或已入库文档问题，并带上具体关键词，例如年假、考勤、报销、采购、论文题目或文档名称。",
            "route": "non_knowledge_base",
        }

    if cjk_count < 2 and alnum_count < 4:
        return {
            "mode": "chat",
            "answer": "问题有点短，请补充想咨询的制度场景、文档名称或关键词。",
            "route": "too_short",
        }

    return None


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


class PolicyRAGService:
    """RAG service core class (singleton)."""

    def __init__(self):
        self.embed_model = None
        self._llm_client = None
        self._has_api_key = False
        self._initialized = False

    def initialize(self) -> Dict[str, Any]:
        if self._initialized:
            return self._status()

        log.info("Initializing PolicyRAGService (PostgreSQL + pgvector)")

        log.info("[RAG] Loading BGE embedding model...")
        from llama_index.embeddings.huggingface import HuggingFaceEmbedding

        self.embed_model = HuggingFaceEmbedding(
            model_name=EMBED_MODEL_NAME,
            query_instruction="为这个句子生成表示以用于检索相关文章：",
            text_instruction="把这段文章转化成一个向量表示：",
            embed_batch_size=32,
        )
        log.info("[RAG] Embedding model: %s (dim=%d)", EMBED_MODEL_NAME, EMBED_DIM)

        log.info("[RAG] Building BM25 index...")
        from biz_rag.recall.recall_engine import ensure_bm25
        ensure_bm25()
        log.info("[RAG] BM25 index ready")

        api_key = OPENAI_API_KEY
        api_base = OPENAI_API_BASE
        self._has_api_key = bool(api_key and api_key.strip())

        if not self._has_api_key:
            log.warning("[RAG] OPENAI_API_KEY not set -> retrieval-only mode")
        else:
            log.info("[RAG] LLM: %s (%s)", LLM_MODEL, api_base)
            self._llm_client = _QwenClient(
                model=LLM_MODEL,
                api_key=api_key,
                base_url=api_base,
                temperature=LLM_TEMPERATURE,
                max_tokens=LLM_MAX_TOKENS,
            )

        self._initialized = True
        log.info("[RAG] PolicyRAGService initialized")
        return self._status()

    def _status(self) -> Dict[str, Any]:
        try:
            from biz_rag.document.repository import get_chunk_count, list_documents
            chunk_count = get_chunk_count()
            docs = list_documents(status="active")
            doc_count = len(docs)
        except Exception as e:
            log.warning("Failed to get status: %s", e)
            chunk_count = 0
            doc_count = 0

        return {
            "initialized": self._initialized,
            "llm_available": self._has_api_key,
            "embedding_model": EMBED_MODEL_NAME,
            "llm_model": LLM_MODEL if self._has_api_key else "none",
            "vector_store": "pgvector HNSW (PostgreSQL)",
            "metadata_store": "PostgreSQL",
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
        """RAG query main entry."""
        routed = _route_query(user_question)
        if routed:
            return {
                "query": user_question,
                "mode": routed["mode"],
                "answer": routed["answer"],
                "sources": [],
                "retrieval_required": False,
                "retrieval_stats": {"route": routed["route"]},
            }

        if not self._initialized:
            self.initialize()

        k = top_k or TOP_K
        threshold = min_score if min_score is not None else SIMILARITY_THRESHOLD

        result: Dict[str, Any] = {
            "query": user_question,
            "mode": "llm" if self._has_api_key else "retrieval_only",
            "answer": "",
            "sources": [],
            "retrieval_required": True,
        }

        query_vector = self.embed_model.get_query_embedding(user_question)

        from biz_rag.recall.recall_engine import multi_way_retrieve
        retrieval = multi_way_retrieve(
            query=user_question,
            query_vector=query_vector,
            top_k=k,
            retrieve_k=20,
            min_score=threshold,
        )

        result["sources"] = retrieval.sources
        result["retrieval_stats"] = retrieval.retrieval_stats

        if not retrieval.sources:
            result["answer"] = "未找到相关内容，请尝试换一种问法。"
            return result

        context_blocks = [hit["text"] for hit in retrieval.sources]
        context = "\n\n---\n\n".join(context_blocks)

        if self._has_api_key and self._llm_client:
            prompt = SYSTEM_PROMPT.format(context=context, query=user_question)
            try:
                answer = self._llm_client.complete(prompt)
                result["answer"] = answer
            except Exception as e:
                log.exception("LLM call failed")
                result["answer"] = f"查询失败: {e}"
        else:
            result["answer"] = (
                "当前使用直接检索模式（未配置 OPENAI_API_KEY），"
                "以上为检索到的原文摘录。如需获得 LLM 智能回答，请配置 API Key。\n\n"
                f"检索结果：\n{context}"
            )
            result["mode"] = "retrieval_only"

        return result


_service: Optional[PolicyRAGService] = None


def get_rag_service() -> PolicyRAGService:
    global _service
    if _service is None:
        _service = PolicyRAGService()
    return _service


def query_policy(user_question: str) -> str:
    """CLI compatible function."""
    svc = get_rag_service()
    return svc.query(user_question).get("answer", "")


def reset_rag_service() -> None:
    """Reset service to uninitialized state."""
    global _service
    if _service is not None:
        _service._initialized = False
