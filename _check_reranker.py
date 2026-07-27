"""
Check reranker model availability
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"D:\Acode\HN_Agent")

# Check transformers / sentence-transformers version
import transformers
import sentence_transformers
print(f"transformers: {transformers.__version__}")
print(f"sentence_transformers: {sentence_transformers.__version__}")

# Check if model files exist
from pathlib import Path
hf_cache = Path.home() / ".cache" / "huggingface"
print(f"\nHF cache: {hf_cache}")

# Check bge-reranker-v2-m3
reranker_path = hf_cache / "hub" / "models--BAAI--bge-reranker-v2-m3"
if reranker_path.exists():
    print(f"bge-reranker-v2-m3: EXISTS")
    # Check key files
    for f in ["config.json", "model.safetensors"]:
        fp = reranker_path / "snapshots" / "main" / f
        if fp.exists():
            print(f"  {f}: {fp.stat().st_size // 1024 // 1024} MB")
else:
    print("bge-reranker-v2-m3: NOT FOUND locally, will download (~400MB)")

# Check other reranker options
reranker_small = hf_cache / "hub" / "models--BAAI--bge-reranker-v2-mini-m3"
if reranker_small.exists():
    print(f"bge-reranker-v2-mini-m3: EXISTS")
else:
    print("bge-reranker-v2-mini-m3: NOT FOUND")

# Check if we can import the reranker
try:
    from sentence_transformers import CrossEncoder
    print("\nCrossEncoder: available")
except ImportError as e:
    print(f"\nCrossEncoder: MISSING - {e}")
