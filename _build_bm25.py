import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"D:\Acode\HN_Agent")

print("Building BM25 index...")
import recall
recall.build_bm25_index()
print(f"BM25 chunks: {len(recall._bm25_corpus)}")
print("BM25 index ready")
