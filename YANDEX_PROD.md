# ExplainLaw — прод на Yandex Cloud (без VPS)

VPS больше не используется. Прод-целевая схема: **Yandex Managed PostgreSQL + Yandex Managed Kafka (Qwen) + MinIO** (отдельный хост/Object Storage).

## 1. Инфраструктура

| Компонент | Куда |
|-----------|------|
| PostgreSQL | Yandex Managed PG (`DATABASE_URL`, `DATABASE_SSLMODE=require`) |
| Kafka | Yandex Managed Kafka SASL_SSL (`KAFKA_*`, `LLM_TRANSPORT=kafka`) |
| Сырьё PDF | MinIO / S3-совместимое хранилище (`MINIO_*`) |
| Qwen worker | Подписчик `llm.requests` → `llm.responses` |
| Gateway | Облачный OpenAI-совместимый API для публичных сводок |
| Cron | Любой хост с Python 3.11+ и доступом к PG/Kafka/MinIO |

Миграции: `alembic upgrade head` (или `python scripts/init_infra.py` если Kafka/MinIO доступны).

## 2. Конфиг

```bash
cp .env.example .env
# заполнить Yandex PG, Kafka, MinIO, Gateway, алерты
pip install -e ".[dev,ocr]"   # + paddle при необходимости: pip install -e ".[paddle]"
```

Ключевые переменные:

- `LLM_TRANSPORT=kafka` + `KAFKA_PIPELINE_EVENTS=false` — если ACL только на `llm.*`
- `OCR_ENGINE=paddle|tesseract|yandex` — публичного SberOCR API **нет**
- `TELEGRAM_*` / `ALERT_WEBHOOK_URL` / `ALERT_LOG_PATH` — алерты §11
- `PUBLISH_EXPORT_DIR=logs/published` — экспорт еженедельного дайджеста

## 3. Cron (прод)

```bash
chmod +x scripts/*_prod.sh scripts/backup_minio.sh scripts/install-cron.sh
./scripts/install-cron.sh --prod
# или посмотреть: ./scripts/install-cron.sh --prod --print
```

Расписание:

- ежедневно 08:00 — `daily_prod.sh`
- понедельник 09:00 — `daily_prod.sh --weekly-publish` (дайджест + mark published + export)
- воскресенье 03:00 — `backfill_prod.sh` (PDF/TIFF + deltas --resume)
- каждые 6 ч — `health_prod.sh --alert`
- воскресенье 02:00 — `backup_minio.sh`

## 4. TIFF-ZIP (старые акты ~2011–2012)

`/File/pdf/{eo}` иногда отдаёт ZIP с TIFF, не PDF. Конвейер:

1. `download_raw_file` → детект `tiff_zip`
2. сохранение ZIP в MinIO
3. `tiff_zip_to_pdf` (компактный JPEG, max width 1600)
4. сохранение PDF и обычный OCR/текст

Догон: `explainlaw backfill-pdfs --limit 200`

## 5. Команды догона

```bash
explainlaw backfill-pdfs --limit 200
RUN_OCR=1 ./scripts/backfill_prod.sh          # OCR + deltas
explainlaw rebuild-deltas --resume --limit 500
explainlaw refresh-summaries --limit 50
explainlaw gate --amendments-only --limit 100
explainlaw publish --mark-published
explainlaw health --alert
explainlaw status
```

## 6. Критерии готовности (§11) — чеклист

- [ ] Ежедневный `collect` пишет в Yandex PG, сырьё в MinIO
- [ ] PDF/OCR (включая TIFF-ZIP) работает
- [ ] Дельты + `missing_acts_queue` наполняются через Qwen/Kafka
- [ ] Оба гейта (механика + LLM verify) → `post_bank`
- [ ] Еженедельный дайджест с `source_url`, экспорт в `logs/published`
- [ ] Алерты на тихий сбор (webhook/Telegram/jsonl)
- [ ] Backup MinIO по cron
- [ ] Домашний сервер Qwen — **не** единственное хранилище данных

## 7. Что нельзя забыть

1. Пересоздать/перенести MinIO — старый VPS мёртв, PDF нужно либо восстановить из бэкапа, либо `collect --all` + `backfill-pdfs`.
2. CA-сертификат Yandex для Kafka/PG (`KAFKA_SSL_CA_LOCATION`, sslmode).
3. Gateway ключи для публичных сводок; без них — механический/Qwen fallback.
