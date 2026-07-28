#!/usr/bin/env bash
set -euo pipefail

echo "[entrypoint] Waiting for PostgreSQL at ${DB_HOST}:${DB_PORT}..."
python - <<'PY'
import os
import time
import psycopg2

deadline = time.time() + int(os.getenv("DB_WAIT_TIMEOUT", "120"))
last_error = None
while time.time() < deadline:
    try:
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "postgres"),
            port=int(os.getenv("DB_PORT", "5432")),
            dbname=os.getenv("DB_NAME", "ragdb"),
            user=os.getenv("DB_USER", "raguser"),
            password=os.getenv("DB_PASSWORD", "ragpass"),
            connect_timeout=3,
        )
        conn.close()
        print("[entrypoint] PostgreSQL is reachable.")
        break
    except Exception as exc:
        last_error = exc
        time.sleep(2)
else:
    raise SystemExit(f"PostgreSQL wait timeout: {last_error}")
PY

echo "[entrypoint] Initializing database schema..."
python init_db.py

if [[ "${AUTO_INGEST:-0}" == "1" ]]; then
  echo "[entrypoint] AUTO_INGEST=1, ingesting /app/data..."
  python data_ingestion.py || echo "[entrypoint] ingestion failed; API will still start"
else
  echo "[entrypoint] AUTO_INGEST is off. Upload documents from the UI or run data_ingestion.py manually."
fi

echo "[entrypoint] Starting API..."
exec uvicorn server:app --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}"
