"""
_diagnose_chunks.py - 全面诊断当前 chunk 质量
"""
import sys, re, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"D:\Acode\HN_Agent")
import database

OUT = open(r"D:\Acode\HN_Agent\_diagnose_out.txt", "w", encoding="utf-8")
def p(*args, **kwargs):
    print(*args, **kwargs, file=OUT)

p("=" * 70)
p("CHUNK DIAGNOSTIC")
p("=" * 70)

with database._PooledConn() as conn:
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM chunks;")
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM chunks WHERE embedding IS NULL;")
    no_vec = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM chunks WHERE LENGTH(text) < 30;")
    tiny = cur.fetchone()[0]

    p(f"\n总 chunks: {total}")
    p(f"无向量: {no_vec}")
    p(f"短文本(<30字): {tiny}")

    p("\n--- 所有 chunk ---")
    cur.execute("""
        SELECT c.id, c.text, LENGTH(c.text) as llen, d.filename, c.chunk_index
        FROM chunks c JOIN documents d ON d.id = c.document_id
        ORDER BY d.filename, c.chunk_index
    """)
    cols = [d[0] for d in cur.description]
    for row in cur.fetchall():
        r = dict(zip(cols, row))
        text = r["text"]
        cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
        ratio = cjk / max(len(text), 1)
        flag = " [BAD-CJK]" if ratio < 0.2 and len(text) > 10 else ""
        flag += " [SHORT]" if len(text) < 50 else ""
        p(f"\n  [{r['llen']:4d}]{flag} {r['filename']}  idx={r['chunk_index']}  cjk={cjk:.0%}")
        preview = text[:200].replace("\n", "\\n")
        p(f"    {preview!r}{'...' if len(text) > 200 else ''}")

    p("\n--- 乱码 chunks（汉字<20%，len>10）---")
    cur.execute("SELECT id, text, LENGTH(text) as llen FROM chunks;")
    cols2 = [d[0] for d in cur.description]
    bad_ids = []
    for row in cur.fetchall():
        r = dict(zip(cols2, row))
        text = r["text"]
        cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
        ratio = cjk / max(len(text), 1)
        if ratio < 0.2 and r["llen"] > 10:
            bad_ids.append(r["id"])
            p(f"  BAD id={r['id'][:8]}  cjk={cjk}  len={r['llen']}")
            p(f"    {r['text'][:120]!r}")
    p(f"\n  共 {len(bad_ids)} 个乱码 chunk")
    p(f"  IDs: {bad_ids}")

OUT.close()
print("Done. See _diagnose_out.txt")
