# ExplainLaw — база НПА (Шаг 1)

Ежедневный сбор ФЗ с [publication.pravo.gov.ru](http://publication.pravo.gov.ru), обработка, гейты, еженедельная публикация в Telegram.

**Репо:** https://github.com/explain-law/regulatory-legal-acts

## Прод (Docker + Yandex)

```bash
cp .env.example .env   # Yandex PG / Kafka / Object Storage / Telegram
sudo docker compose up -d --build
sudo docker compose exec app alembic upgrade head
sudo docker compose exec app explainlaw status
```

Подымаются **app** (API :8000) и **cron** (daily/weekly/health).  
Локальные Postgres/MinIO/Kafka **не** стартуют.

Полная инструкция: **[YANDEX_PROD.md](YANDEX_PROD.md)**.

## Локально (инфра в Docker)

```bash
cp .env.example .env
docker compose --profile local up -d --build
```

## Документация

| Файл | О чём |
|------|--------|
| [YANDEX_PROD.md](YANDEX_PROD.md) | Прод-runbook |
| [PROD_HANDOFF.md](PROD_HANDOFF.md) | Исторический handoff |
| [rule.md](rule.md) | ТЗ |
