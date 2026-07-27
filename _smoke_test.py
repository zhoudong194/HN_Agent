"""End-to-end smoke test for the FastAPI server."""
import json
import sys
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:8000"


def call(method, path, data=None, headers=None):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(data).encode("utf-8") if data is not None else None,
        headers={"Content-Type": "application/json", **(headers or {})},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


print("=" * 60)
print("END-TO-END SMOKE TEST")
print("=" * 60)

# 1. Health
print("\n[1] GET /api/health")
code, h = call("GET", "/api/health")
print(f"  Status: {code}")
print(f"  Body: {json.dumps(h, ensure_ascii=False, indent=2)}")

# 2. Documents
print("\n[2] GET /api/documents")
code, docs = call("GET", "/api/documents")
print(f"  Status: {code}")
print(f"  Document count: {len(docs)}")
for d in docs:
    print(f"    - {d['filename']} ({d['file_type']}, {d['size_bytes']} bytes)")

# 3. Query (Chinese)
print("\n[3] POST /api/query")
code, out = call("POST", "/api/query", {
    "question": "请问我有多少天年假？有什么请假制度？",
    "top_k": 5,
})
print(f"  Status: {code}")
print(f"  Mode: {out.get('mode')}")
print(f"  Sources: {len(out.get('sources', []))}")
print("  Answer (first 300 chars):")
print("    " + out.get("answer", "")[:300].replace("\n", "\n    "))
if out.get("sources"):
    s = out["sources"][0]
    print(f"  Top source score: {s.get('score')}")
    print(f"  Top source text: {s['text'][:150]}")

# 4. Query (English-ish numeric)
print("\n[4] POST /api/query (numeric answer)")
code, out = call("POST", "/api/query", {
    "question": "工作日加班工资按几倍支付？",
    "top_k": 3,
})
print(f"  Status: {code}")
print(f"  Mode: {out.get('mode')}")
print("  Answer (first 200 chars):")
print("    " + out.get("answer", "")[:200].replace("\n", "\n    "))

# 5. UI HTML (just first 80 chars to prove it serves)
print("\n[5] GET /")
req = urllib.request.Request(BASE + "/", method="GET")
with urllib.request.urlopen(req, timeout=10) as r:
    html = r.read().decode("utf-8")
print(f"  HTTP status: {r.status}")
print(f"  Content-Type: {r.headers.get('Content-Type')}")
print(f"  Body length: {len(html)} chars")
print(f"  Title: {html.split('<title>')[1].split('</title>')[0] if '<title>' in html else 'N/A'}")

print("\n" + "=" * 60)
print("ALL CHECKS PASSED" if code == 200 and h.get("initialized") else "SOME CHECKS FAILED")
print("=" * 60)
