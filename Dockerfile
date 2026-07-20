# syntax=docker/dockerfile:1
FROM python:3.11-slim-bookworm

ARG TARGETARCH=amd64

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates \
      curl \
      libpq5 \
      tesseract-ocr \
      tesseract-ocr-rus \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL -o /usr/local/bin/supercronic \
      "https://github.com/aptible/supercronic/releases/download/v0.2.33/supercronic-linux-${TARGETARCH}" \
    && chmod +x /usr/local/bin/supercronic

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./
COPY scripts ./scripts
COPY docker ./docker

RUN pip install --no-cache-dir -e ".[ocr]"

ENV PYTHONUNBUFFERED=1 \
    OCR_ENGINE=tesseract \
    PUBLISH_EXPORT_DIR=/app/logs/published \
    ALERT_LOG_PATH=/app/logs/alerts.jsonl

RUN mkdir -p /app/logs/published

# По умолчанию — API; cron-сервис переопределяет command
CMD ["explainlaw", "serve", "--host", "0.0.0.0", "--port", "8000"]
