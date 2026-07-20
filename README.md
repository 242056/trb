# ExplainLaw — база НПА (Шаг 1)

Ежедневный сбор ФЗ с [publication.pravo.gov.ru](http://publication.pravo.gov.ru), извлечение текста, дельты изменений, гейты качества, еженедельная публикация.

**Репозиторий прода:** https://github.com/explain-law/regulatory-legal-acts

## Быстрый старт (локально)

```bash
cp .env.example .env
docker compose --profile local up -d
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python scripts/init_infra.py
explainlaw status
explainlaw daily
```

`docker compose up` без `--profile local` → `no service selected` (на проде так и должно быть).

## Прод

Полная инструкция: **[YANDEX_PROD.md](YANDEX_PROD.md)**  
(Yandex PG + Kafka + Object Storage, cron, OCR, Telegram, без Docker.)

```bash
cp .env.example .env    # заполнить секреты
pip install -e ".[dev,ocr]"
alembic upgrade head
./scripts/install-cron.sh --prod
```

## Документация

| Файл | О чём |
|------|--------|
| [YANDEX_PROD.md](YANDEX_PROD.md) | **Прод-runbook** (актуальный) |
| [PROD_HANDOFF.md](PROD_HANDOFF.md) | Историческая передача / перенос данных |
| [rule.md](rule.md) | Техническое задание |

## Данные не в git

Секреты (`.env`), архивы MinIO (`*.tar.gz`) и PDF — только вне репозитория. Сырьё на проде уже в Yandex Object Storage `explain-npa`.
