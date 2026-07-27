"""
_smoke_net.py - Smoke test for network principle lab manual RAG.
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from rag_service import initialize_rag, get_service

print("=" * 60)
print("RAG Smoke Test - 网络原理实验")
print("=" * 60)

svc = get_service()
svc.initialize()
status = svc.get_status()
print(f"Chunks: {status['chunk_count']}, Docs: {status['document_count']}")
print()

tests = [
    "网络原理实验有哪些内容？",
    "实验的评分标准是什么？",
]

for q in tests:
    print(f"\n[Query] {q}")
    result = svc.query(q)
    print(f"Mode: {result['mode']} | Sources: {len(result['sources'])}")
    print(f"Answer:\n{result['answer'][:400]}")
    print()
