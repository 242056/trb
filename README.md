# ExplainLaw — база НПА (Шаг 1)

Ежедневный сбор ФЗ с [publication.pravo.gov.ru](http://publication.pravo.gov.ru), извлечение текста, дельты изменений, гейты качества, еженедельная публикация.

## Быстрый старт

```bash
cp .env.example .env
# Локально (Postgres/MinIO/Kafka в Docker):
docker compose --profile local up -d
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python scripts/init_infra.py
explainlaw status
explainlaw daily
```

На проде с Yandex PG/Kafka/Object Storage compose **не нужен** — только `.env` и `./scripts/install-cron.sh --prod`.  
`docker compose up` без `--profile local` ничего не поднимет (образы не качает).

## Прод (без локального Docker)

Целевая схема: Yandex Managed PostgreSQL + Yandex Kafka (Qwen) + Object Storage.

```bash
cp .env.example .env   # заполнить Yandex / AWS_* / Gateway / алерты
./scripts/install-cron.sh --prod
```

Подробно: [YANDEX_PROD.md](YANDEX_PROD.md).

- [YANDEX_PROD.md](YANDEX_PROD.md) — прод на Yandex Cloud, cron, TIFF-ZIP, OCR
- [PROD_HANDOFF.md](PROD_HANDOFF.md) — передача на прод, перенос БД и MinIO
- [rule.md](rule.md) — техническое задание

## Данные не в git

Бэкапы БД (`.dump`, `.sql`) и `minio_data.tar.gz` передаются отдельно — см. PROD_HANDOFF.md.
