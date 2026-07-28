# syntax=docker/dockerfile:1
# ================================================================
# Dockerfile - HN_Agent RAG API
# Multi-arch ready: builds on linux/amd64 and linux/arm64.
# ================================================================

FROM python:3.11-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt


FROM python:3.11-slim-bookworm

LABEL org.opencontainers.image.title="HN_Agent"
LABEL org.opencontainers.image.description="Enterprise policy RAG API with FastAPI, PostgreSQL and pgvector"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    DEBIAN_FRONTEND=noninteractive \
    HF_HOME=/app/.cache/huggingface \
    TRANSFORMERS_CACHE=/app/.cache/huggingface \
    SENTENCE_TRANSFORMERS_HOME=/app/.cache/sentence-transformers

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

COPY auth.py .
COPY config.py .
COPY database.py .
COPY data_ingestion.py .
COPY init_db.py .
COPY rag_query.py .
COPY rag_service.py .
COPY rbac.py .
COPY rbac_routes.py .
COPY recall.py .
COPY server.py .
COPY schema.sql .
COPY _rbac_init.sql .
COPY docker-entrypoint.sh .
COPY static/ ./static/

RUN mkdir -p /app/data /app/models /app/.cache/huggingface /app/.cache/sentence-transformers \
    && chmod +x /app/docker-entrypoint.sh

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD curl -fsS http://localhost:${PORT:-8000}/api/health || exit 1

ENTRYPOINT ["bash", "/app/docker-entrypoint.sh"]
