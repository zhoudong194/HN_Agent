"""
db_inspect.py - 数据库可视化检查工具

用法:
    python db_inspect.py              # 查看概览
    python db_inspect.py --docs       # 列出所有文档
    python db_inspect.py --chunks    # 列出所有 chunk
    python db_inspect.py --index     # 查看 FAISS 索引信息
    python db_inspect.py --sample N  # 查看前 N 条 chunk 详情
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import argparse

# Add parent dir to path for config import
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
import database
import faiss


def print_header(title: str):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def cmd_docs():
    """列出所有文档记录。"""
    print_header("Documents Table")
    docs = database.list_documents(status=None, limit=1000)
    if not docs:
        print("  (empty)")
        return

    print(f"  {'ID':<38} {'文件名':<30} {'类型':<6} {'状态':<10} {'上传时间':<25}")
    print(f"  {'-'*38} {'-'*30} {'-'*6} {'-'*10} {'-'*25}")
    for d in docs:
        fname = d["filename"][:28]
        t = d["uploaded_at"][:19]
        print(f"  {d['id']:<38} {fname:<30} {d['file_type']:<6} {d['status']:<10} {t:<25}")

    print(f"\n  Total: {len(docs)} documents")


def cmd_chunks():
    """列出所有 chunk 记录。"""
    print_header("Chunks Table")
    import sqlite3
    conn = sqlite3.connect(str(config.APP_DIR / "rag_meta.db"))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    rows = cur.execute("""
        SELECT c.id, c.document_id, c.text, c.header_1, c.header_2,
               c.chunk_index, d.filename
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        ORDER BY d.uploaded_at, c.chunk_index
    """).fetchall()

    if not rows:
        print("  (empty)")
        conn.close()
        return

    print(f"  {'#':<4} {'文档':<28} {'标题层级':<35} {'文本预览':<30}")
    print(f"  {'-'*4} {'-'*28} {'-'*35} {'-'*30}")
    for i, row in enumerate(rows, 1):
        h = "/".join(x for x in [row["header_1"], row["header_2"]] if x) or "(无标题)"
        preview = row["text"].replace("\n", " ")[:28]
        print(f"  {i:<4} {row['filename'][:26]:<28} {h[:33]:<35} {preview:<30}")

    print(f"\n  Total: {len(rows)} chunks")
    conn.close()


def cmd_index():
    """查看 FAISS 索引信息。"""
    print_header("FAISS HNSW Index")

    idx_path = config.APP_DIR / "faiss_index" / "hnsw.index"
    meta_path = config.APP_DIR / "faiss_index" / "hnsw_meta.json"

    if not idx_path.exists():
        print("  FAISS index file not found.")
        return

    index = faiss.read_index(str(idx_path))
    print(f"  索引文件: {idx_path}")
    print(f"  向量维度: {index.d}")
    print(f"  向量总数: {index.ntotal}")
    print(f"  HNSW m: {index.hnsw.m}")
    print(f"  HNSW efConstruction: {index.hnsw.efConstruction}")

    # 元数据
    if meta_path.exists():
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        print(f"\n  元数据条目数: {len(meta)}")

        # 按文档分组统计
        doc_counts: dict = {}
        for m in meta.values():
            doc_id = m["document_id"]
            doc_counts[doc_id] = doc_counts.get(doc_id, 0) + 1

        print(f"\n  每文档 chunk 数量:")
        conn = sqlite3.connect(str(config.APP_DIR / "rag_meta.db"))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        for doc_id, cnt in doc_counts.items():
            row = cur.execute("SELECT filename FROM documents WHERE id=?", (doc_id,)).fetchone()
            fname = row["filename"] if row else "(未知)"
            print(f"    {fname}: {cnt} chunks")
        conn.close()
    else:
        print("  元数据文件不存在")


def cmd_sample(n: int):
    """查看前 N 条 chunk 的完整内容。"""
    print_header(f"Sample Chunks (前 {n} 条)")

    import sqlite3
    conn = sqlite3.connect(str(config.APP_DIR / "rag_meta.db"))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    rows = cur.execute("""
        SELECT c.id, c.text, c.header_1, c.header_2, c.header_3,
               c.chunk_index, c.source_file, d.filename, d.category
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        ORDER BY c.id
        LIMIT ?
    """, (n,)).fetchall()

    for i, row in enumerate(rows, 1):
        print(f"\n  [{i}] {row['filename']}")
        if row["header_1"]:
            print(f"      H1: {row['header_1']}")
        if row["header_2"]:
            print(f"      H2: {row['header_2']}")
        if row["header_3"]:
            print(f"      H3: {row['header_3']}")
        print(f"      文本长度: {len(row['text'])} 字符")
        print(f"      内容:")
        for line in row["text"].split("\n")[:6]:
            print(f"        {line[:80]}")
        if len(row["text"].split("\n")) > 6:
            print(f"        ... (共 {len(row['text'].split(chr(10)))} 行)")

    conn.close()


def cmd_overview():
    """总览。"""
    print_header("Database Overview")

    import sqlite3
    conn = sqlite3.connect(str(config.APP_DIR / "rag_meta.db"))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 文档统计
    total_docs = cur.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    active_docs = cur.execute("SELECT COUNT(*) FROM documents WHERE status='active'").fetchone()[0]
    archived_docs = cur.execute("SELECT COUNT(*) FROM documents WHERE status='archived'").fetchone()[0]

    # chunk 统计
    total_chunks = cur.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]

    # 分类
    cats = cur.execute("""
        SELECT DISTINCT category FROM documents
        WHERE category IS NOT NULL AND category != '' AND status='active'
    """).fetchall()
    categories = [r[0] for r in cats]

    print(f"  📄 文档总数: {total_docs}  (active={active_docs}, archived={archived_docs})")
    print(f"  📦 Chunk 总数: {total_chunks}")
    print(f"  🏷️  分类: {', '.join(categories) or '(无)'}")

    # 文件大小
    data_dir = Path(config.DATA_DIR)
    if data_dir.exists():
        files = [f for f in data_dir.iterdir() if f.is_file() and f.suffix.lower() in {".doc", ".docx", ".md"}]
        total_size = sum(f.stat().st_size for f in files)
        print(f"\n  📁 data/ 源文件:")
        for f in files:
            size_mb = f.stat().st_size / 1024 / 1024
            print(f"    {f.name}: {size_mb:.2f} MB")
        print(f"    总计: {total_size / 1024 / 1024:.2f} MB")

    # FAISS 索引
    idx_path = config.APP_DIR / "faiss_index" / "hnsw.index"
    if idx_path.exists():
        index = faiss.read_index(str(idx_path))
        print(f"\n  🔢 FAISS 索引:")
        print(f"    向量数: {index.ntotal}, 维度: {index.d}")
        print(f"    HNSW m={index.hnsw.m}, ef={index.hnsw.efConstruction}")
        print(f"    文件大小: {idx_path.stat().st_size / 1024 / 1024:.2f} MB")

    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Database inspection tool")
    parser.add_argument("--docs", action="store_true", help="List all documents")
    parser.add_argument("--chunks", action="store_true", help="List all chunks")
    parser.add_argument("--index", action="store_true", help="Show FAISS index info")
    parser.add_argument("--sample", type=int, default=0, metavar="N",
                        help="Show first N chunk details")
    args = parser.parse_args()

    if args.docs:
        cmd_docs()
    elif args.chunks:
        cmd_chunks()
    elif args.index:
        cmd_index()
    elif args.sample > 0:
        cmd_sample(args.sample)
    else:
        cmd_overview()
