# ================================================================
# Dockerfile — Company Rules RAG System (PostgreSQL + pgvector)
#
# Multi-stage build:
#   stage 1  — download models (~330 MB)
#   stage 2  — production runtime image
# ================================================================
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build dependencies (for sentencepiece / torch)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


# ================================================================
FROM python:3.11-slim

LABEL maintainer="HN_Agent"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY config.py .
COPY database.py .
COPY rag_service.py .
COPY data_ingestion.py .
COPY server.py .
COPY rag_query.py .
COPY init_db.py .
COPY static/ ./static/
COPY .env.example .env.template

# Pre-download BGE embedding model on first run (done at startup via entrypoint)
ENV HF_HUB_OFFLINE=0
ENV TRANSFORMERS_OFFLINE=0

# Entrypoint: init DB on first start, then run server
ENTRYPOINT ["/bin/bash", "-c"]
CMD [\
    "python init_db.py && \
     python data_ingestion.py && \
     uvicorn server:app --host 0.0.0.0 --port 8000"\
]
