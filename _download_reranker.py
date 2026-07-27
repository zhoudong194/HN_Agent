import os
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"
from huggingface_hub import snapshot_download
print("Downloading BAAI/bge-reranker-base via hf-mirror.com...")
snapshot_download(
    "BAAI/bge-reranker-base",
    local_dir=r"D:\Acode\HN_Agent\models\bge-reranker-base",
)
print("Done")
