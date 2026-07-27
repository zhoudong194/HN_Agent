"""
config.py - Centralized configuration loader.

Reads variables from:
  1. Process environment  (highest priority - for production / Docker)
  2. .env file in project root (for local development)

This module is the single source of truth for all runtime configuration.
Other modules should import from here instead of calling os.getenv directly.
"""

from pathlib import Path
import os
from dotenv import load_dotenv

# Locate .env at project root (same dir as config.py)
APP_DIR = Path(__file__).resolve().parent
ENV_PATH = APP_DIR / ".env"

# Load .env into os.environ (does NOT override already-set real env vars)
load_dotenv(dotenv_path=ENV_PATH, override=False)


def _get(key: str, default: str = "") -> str:
    """Read an env var with a default fallback. Strips whitespace."""
    val = os.getenv(key, default)
    return val.strip() if isinstance(val, str) else val


# ----------------------------------------------------------------------
# Server / hosting
# ----------------------------------------------------------------------
HOST: str = _get("HOST", "0.0.0.0")
PORT: int = int(_get("PORT", "8000"))

# ----------------------------------------------------------------------
# LLM (OpenAI-compatible API)
# ----------------------------------------------------------------------
# Required: provide either OPENAI_API_KEY, or leave empty for retrieval-only mode.
OPENAI_API_KEY: str = _get("OPENAI_API_KEY", "")

# Default to 阿里云通义千问 (Qwen), which is Chinese-optimized and cost-effective.
# Change this + OPENAI_API_BASE to switch to OpenAI / DeepSeek / Azure / vLLM.
OPENAI_API_BASE: str = _get("OPENAI_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1")
LLM_MODEL: str = _get("LLM_MODEL", "qwen-plus")
LLM_TEMPERATURE: float = float(_get("LLM_TEMPERATURE", "0.1"))
LLM_MAX_TOKENS: int = int(_get("LLM_MAX_TOKENS", "1024"))

# ----------------------------------------------------------------------
# Embedding model
# ----------------------------------------------------------------------
EMBED_MODEL_NAME: str = _get("EMBED_MODEL_NAME", "BAAI/bge-large-zh-v1.5")
EMBED_DIM: int = int(_get("EMBED_DIM", "1024"))

# Optional: HuggingFace token to speed up model downloads / bypass rate limits
HF_TOKEN: str = _get("HF_TOKEN", "")

# ----------------------------------------------------------------------
# Vector store
# ----------------------------------------------------------------------
CHROMA_PERSIST_DIR: str = _get("CHROMA_PERSIST_DIR", "./chroma_db")
COLLECTION_NAME: str = _get("COLLECTION_NAME", "rules_vectors")

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
    """Whether the LLM can be invoked (an API key was provided)."""
    return bool(OPENAI_API_KEY)


def is_custom_api_base() -> bool:
    """Whether OPENAI_API_BASE differs from the OpenAI public endpoint."""
    return OPENAI_API_BASE.rstrip("/") != "https://api.openai.com/v1"


def status_summary() -> dict:
    """Non-sensitive summary of the active configuration (safe to log / expose)."""
    return {
        "host": HOST,
        "port": PORT,
        "llm_model": LLM_MODEL if has_llm_key() else "none",
        "llm_api_base": OPENAI_API_BASE if is_custom_api_base() else "default(openai)",
        "llm_key_configured": has_llm_key(),
        "embedding_model": EMBED_MODEL_NAME,
        "chroma_dir": CHROMA_PERSIST_DIR,
        "collection": COLLECTION_NAME,
        "top_k": TOP_K,
        "data_dir": DATA_DIR,
    }


if __name__ == "__main__":
    # Quick sanity check: `python config.py`
    import json
    print(json.dumps(status_summary(), indent=2, ensure_ascii=False))