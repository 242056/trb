# syntax=docker/dockerfile:1
FROM python:3.11-slim-bookworm

ARG TARGETARCH

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates \
      curl \
      libpq5 \
      tesseract-ocr \
      tesseract-ocr-rus \
    && mkdir -p /usr/local/share/ca-certificates/Yandex \
    && curl -fsSL -o /usr/local/share/ca-certificates/Yandex/YandexInternalRootCA.crt \
      "https://storage.yandexcloud.net/cloud-certs/CA.pem" \
    && chmod 0644 /usr/local/share/ca-certificates/Yandex/YandexInternalRootCA.crt \
    && rm -rf /var/lib/apt/lists/* \
    && ARCH="${TARGETARCH:-amd64}" \
    && case "$ARCH" in amd64|arm64) ;; *) ARCH=amd64 ;; esac \
    && curl -fsSL -o /usr/local/bin/supercronic \
      "https://github.com/aptible/supercronic/releases/download/v0.2.33/supercronic-linux-${ARCH}" \
    && chmod +x /usr/local/bin/supercronic \
    && printf '%s\n' '* * * * * true' > /tmp/sc-test.cron \
    && /usr/local/bin/supercronic -test /tmp/sc-test.cron \
    && rm -f /tmp/sc-test.cron

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./
COPY scripts ./scripts
COPY docker ./docker

# С части VPS (Yandex и др.) pypi.org даёт ReadTimeout на setuptools.
# Зеркало по умолчанию; переопределение: --build-arg PIP_INDEX_URL=...
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple
ARG PIP_TRUSTED_HOST=mirrors.aliyun.com
ENV PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST} \
    PIP_DEFAULT_TIMEOUT=60 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
RUN pip install --no-cache-dir --retries 5 --upgrade pip setuptools wheel \
    && pip install --no-cache-dir --retries 5 ".[ocr]" \
    && chmod +x /app/docker/cron-entrypoint.sh /app/docker/cron-run.sh \
    && test -x /usr/local/bin/explainlaw

ENV PYTHONUNBUFFERED=1 \
    PATH="/usr/local/bin:${PATH}" \
    TZ=Europe/Moscow \
    OCR_ENGINE=tesseract \
    PUBLISH_EXPORT_DIR=/app/logs/published \
    ALERT_LOG_PATH=/app/logs/alerts.jsonl \
    KAFKA_SSL_CA_LOCATION=/usr/local/share/ca-certificates/Yandex/YandexInternalRootCA.crt

RUN mkdir -p /app/logs/published

# По умолчанию — API; cron-сервис переопределяет command
CMD ["explainlaw", "serve", "--host", "0.0.0.0", "--port", "7000"]
