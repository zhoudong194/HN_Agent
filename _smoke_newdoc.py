"""Test that newly uploaded docs can be retrieved."""
import urllib.request
import json

req = urllib.request.Request(
    "http://127.0.0.1:8000/api/query",
    data=json.dumps({"question": "员工有几天事假？", "top_k": 3}).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)

with urllib.request.urlopen(req, timeout=60) as r:
    out = json.loads(r.read())

print("mode =", out["mode"])
print("sources =", len(out["sources"]))
print("--- ANSWER ---")
print(out["answer"][:600])
print()
print("--- TOP SOURCE (newly uploaded should appear) ---")
if out["sources"]:
    s = out["sources"][0]
    print("score =", s.get("score"))
    print("file  =", s["metadata"].get("source_file"))
    print(s["text"][:200])
