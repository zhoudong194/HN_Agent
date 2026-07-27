# ============================================================
# Stage 1: Build stage — install all Python dependencies
# ============================================================
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build dependencies (compiled deps for numpy / torch)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ============================================================
# Stage 2: Runtime stage — slim image with all deps
# ============================================================
FROM python:3.11-slim

WORKDIR /app

# Runtime-only system packages (no compiler needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy pre-installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin             /usr/local/bin

# Copy application code
COPY . .

# Expose FastAPI port
EXPOSE 8000

# Environment: let container env vars override .env defaults
ENV PYTHONUNBUFFERED=1

# ------------------------------------------------------------------
# Volume mounts (bind at runtime via docker-compose or -v):
#   - ./data              : source documents (.docx / .md)
#   - ./chroma_db         : ChromaDB vector store (persistent)
#   - ~/.cache/huggingface: BGE model cache (speeds up restarts)
# ------------------------------------------------------------------
VOLUME ["/app/data", "/app/chroma_db", "/root/.cache/huggingface"]

# Health check: confirm the API responds 200
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" \
    || exit 1

CMD ["python", "server.py"]
