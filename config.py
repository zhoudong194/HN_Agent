"""
config.py - Centralized configuration loader.

Reads variables from:
  1. Process environment  (highest priority - for production / Docker)
  2. .env file in project root (for local development)

This module is the single source of truth for all runtime configuration.
"""

from pathlib import Path
import os
from dotenv import load_dotenv

APP_DIR = Path(__file__).resolve().parent
ENV_PATH = APP_DIR / ".env"

load_dotenv(dotenv_path=ENV_PATH, override=False)


def _get(key: str, default: str = "") -> str:
    val = os.getenv(key, default)
    return val.strip() if isinstance(val, str) else val


# ----------------------------------------------------------------------
# Server
# ----------------------------------------------------------------------
HOST: str = _get("HOST", "0.0.0.0")
PORT: int = int(_get("PORT", "8000"))

# ----------------------------------------------------------------------
# LLM
# ----------------------------------------------------------------------
OPENAI_API_KEY: str = _get("OPENAI_API_KEY", "")

OPENAI_API_BASE: str = _get(
    "OPENAI_API_BASE",
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
)
LLM_MODEL: str = _get("LLM_MODEL", "qwen-plus")
LLM_TEMPERATURE: float = float(_get("LLM_TEMPERATURE", "0.1"))
LLM_MAX_TOKENS: int = int(_get("LLM_MAX_TOKENS", "1024"))

# ----------------------------------------------------------------------
# Embedding
# ----------------------------------------------------------------------
EMBED_MODEL_NAME: str = _get("EMBED_MODEL_NAME", "BAAI/bge-large-zh-v1.5")
EMBED_DIM: int = int(_get("EMBED_DIM", "1024"))
HF_TOKEN: str = _get("HF_TOKEN", "")

# ----------------------------------------------------------------------
# Vector store (FAISS)
# ----------------------------------------------------------------------
FAISS_DIR: str = _get("FAISS_DIR", "./faiss_index")
EMBEDDINGS_DIR: str = _get("EMBEDDINGS_DIR", "./embeddings")

# ----------------------------------------------------------------------
# Metadata store (SQLite)
# ----------------------------------------------------------------------
META_DB_PATH: str = _get("META_DB_PATH", "./rag_meta.db")

# ----------------------------------------------------------------------
# PostgreSQL + pgvector
# ----------------------------------------------------------------------
DB_HOST: str = _get("DB_HOST", "localhost")
DB_PORT: int = int(_get("DB_PORT", "5433"))
DB_NAME: str = _get("DB_NAME", "ragdb")
DB_USER: str = _get("DB_USER", "raguser")
DB_PASSWORD: str = _get("DB_PASSWORD", "ragpass")

# ----------------------------------------------------------------------
# RAG retrieval
# ----------------------------------------------------------------------
TOP_K: int = int(_get("TOP_K", "5"))
SIMILARITY_THRESHOLD: float = float(_get("SIMILARITY_THRESHOLD", "0.0"))

# ----------------------------------------------------------------------
# Data directory
# ----------------------------------------------------------------------
DATA_DIR: str = _get("DATA_DIR", "./data")

# ----------------------------------------------------------------------
# Derived helpers
# ----------------------------------------------------------------------
def has_llm_key() -> bool:
    return bool(OPENAI_API_KEY and OPENAI_API_KEY.strip())


def is_custom_api_base() -> bool:
    return OPENAI_API_BASE.rstrip("/") != "https://api.openai.com/v1"


def status_summary() -> dict:
    return {
        "host": HOST,
        "port": PORT,
        "llm_model": LLM_MODEL if has_llm_key() else "none",
        "llm_api_base": OPENAI_API_BASE if is_custom_api_base() else "default(openai)",
        "llm_key_configured": has_llm_key(),
        "embedding_model": EMBED_MODEL_NAME,
        "vector_store": "pgvector HNSW (PostgreSQL)",
        "metadata_store": "PostgreSQL",
        "db_host": DB_HOST,
        "db_port": DB_PORT,
        "db_name": DB_NAME,
        "top_k": TOP_K,
        "data_dir": DATA_DIR,
    }


if __name__ == "__main__":
    import json
    print(json.dumps(status_summary(), indent=2, ensure_ascii=False))
