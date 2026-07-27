"""
_clean_bad_chunks.py — 删除乱码/孤儿标题/极短 chunk
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"D:\Acode\HN_Agent")
import database

# 要删除的 chunk IDs（乱码 + 极短孤儿标题）
BAD_IDS = [
    # 乱码
    "eefb9d8e-5817-4546-8c09-8ad8866d2e87",  # '# test_policy' 纯英文标题
    "d8fb9ea7-8ad9-4f87-a7da-bf4b2f490b75",  # 71KB '?' 乱码 textract 失败
    # 孤儿标题（只有标题行，len < 20，无正文）
    "f643c4a2-87e4-4a8f-83fb-6ecc9ac1241b",  # '## 第一章 年假制度'
    "eaf8b91a-6fbe-4959-bf78-52e677490ab0",  # '## 第二章 考勤制度'
    "1f6a49a8-215f-4587-a1ce-fd76f87e7de1",  # '## 第三章 报销制度'
    "9f3d7251-8c8a-4636-9e02-3b8ccf75d850",  # '## 第四章 办公用品管理'
]

# 先查出来
print("查询孤儿标题 chunk...")
with database._PooledConn() as conn:
    cur = conn.cursor()
    cur.execute("""
        SELECT c.id, c.text, LENGTH(c.text) as llen, d.filename, c.chunk_index
        FROM chunks c JOIN documents d ON d.id = c.document_id
        WHERE LENGTH(c.text) < 30
        ORDER BY d.filename, c.chunk_index
    """)
    cols = [d[0] for d in cur.description]
    orphan_ids = []
    for row in cur.fetchall():
        r = dict(zip(cols, row))
        text = r["text"].strip()
        # 纯标题行（不含句号、逗号、数字列表等正文特征）
        is_orphan = (
            r["llen"] < 30
            and not any(p in text for p in ["。", "，", "：", "；", "、", ". ", ", "])
        )
        if is_orphan:
            orphan_ids.append(r["id"])
            print(f"  ORPHAN [{r['llen']:2d}] {r['filename']} idx={r['chunk_index']}: {text!r}")

    bad_all = set(BAD_IDS) | set(orphan_ids)
    print(f"\n共 {len(bad_all)} 个坏 chunk 需要删除:")
    for bid in bad_all:
        print(f"  - {bid}")

    if not bad_all:
        print("无需清理")
        sys.exit(0)

    # DELETE
    placeholders = ",".join(["%s"] * len(bad_all))
    cur.execute(f"DELETE FROM chunks WHERE id IN ({placeholders})", list(bad_all))
    conn.commit()
    deleted = cur.rowcount

    # 验证
    cur.execute("SELECT COUNT(*) FROM chunks;")
    remaining = cur.fetchone()[0]

print(f"\n已删除: {deleted}")
print(f"剩余 chunks: {remaining}")
