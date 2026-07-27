"""
Find orphan chunk IDs
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"D:\Acode\HN_Agent")
import database

with database._PooledConn() as conn:
    cur = conn.cursor()
    cur.execute("""
        SELECT id, text, LENGTH(text) as llen, chunk_index
        FROM chunks
        WHERE LENGTH(text) < 30
        ORDER BY chunk_index
    """)
    cols = [d[0] for d in cur.description]
    for row in cur.fetchall():
        r = dict(zip(cols, row))
        print(f"ID={r['id']}  LEN={r['llen']}  IDX={r['chunk_index']}  TEXT={r['text']!r}")
