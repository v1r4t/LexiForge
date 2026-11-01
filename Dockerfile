# ---- stage 1: build the dashboard -----------------------------------------
FROM node:20-slim AS web

WORKDIR /web
COPY web/frontend/package.json web/frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund

COPY web/frontend/ ./
RUN npm run build


# ---- stage 2: python runtime ----------------------------------------------
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Copy the package before installing so setuptools can find it.
COPY pyproject.toml README.md ./
COPY lexiforge/ ./lexiforge/
RUN pip install --no-cache-dir .

# Runtime assets
COPY data/ ./data/
COPY scripts/ ./scripts/
COPY web/api.py ./web/api.py
COPY web/data/ ./web/data/
COPY --from=web /web/dist ./web/frontend/dist

RUN mkdir -p /app/audio /app/refs /app/transcripts /app/runs

ENV PYTHONPATH=/app \
    DEMO_MODE=precomputed

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "web.api:app", "--host", "0.0.0.0", "--port", "8000"]
