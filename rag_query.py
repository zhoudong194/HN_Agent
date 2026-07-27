"""
rag_query.py - Thin compatibility wrapper. The real implementation has moved
to rag_service.py so it can be shared between the CLI and the FastAPI backend.

CLI usage (still works):
    python rag_query.py
"""

from rag_service import (
    initialize_rag,
    query_policy,
    get_service,
    PolicyRAGService,
)

__all__ = ["initialize_rag", "query_policy", "get_service", "PolicyRAGService"]


if __name__ == "__main__":
    import sys
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    print("=" * 60)
    print("Policy RAG Query System - Interactive Mode")
    print("=" * 60)
    initialize_rag()
    test_q = "请问我有多少天年假？有什么请假制度？"
    print(f"\n[Test Query] {test_q}")
    print(query_policy(test_q))
