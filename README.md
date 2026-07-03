# ExplainLaw — база НПА (Шаг 1)

Ежедневный сбор ФЗ с [publication.pravo.gov.ru](http://publication.pravo.gov.ru), извлечение текста, дельты изменений, гейты качества, еженедельная публикация.

## Быстрый старт

```bash
cp .env.example .env
docker compose up -d
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python scripts/init_infra.py
explainlaw status
explainlaw daily
```

## Документация

- [PROD_HANDOFF.md](PROD_HANDOFF.md) — передача на прод, перенос БД и MinIO
- [rule.md](rule.md) — техническое задание

## Данные не в git

Бэкапы БД (`.dump`, `.sql`) и `minio_data.tar.gz` передаются отдельно — см. PROD_HANDOFF.md.
