# ExplainLaw — база НПА (Шаг 1)

Ежедневный сбор ФЗ с [publication.pravo.gov.ru](http://publication.pravo.gov.ru), обработка, гейты, еженедельная публикация в Telegram.

**Репо:** https://github.com/explain-law/regulatory-legal-acts  
**Деплой:** ветка `main` → см. **[YANDEX_PROD.md](YANDEX_PROD.md)**

## Прод (Docker + Yandex)

На хосте только приложение. PG / Kafka / S3 — в Yandex.

```bash
git clone https://github.com/explain-law/regulatory-legal-acts.git
cd regulatory-legal-acts
git checkout main && git pull

cp .env.example .env          # заполнить Yandex PG / S3 / Kafka / Telegram
sudo docker compose up -d --build
sudo docker compose exec app alembic upgrade head
./scripts/prod_verify.sh
```

Подымаются **app** (`:7000`) и **cron** (daily 08:00, weekly publish пн 09:00).

Обновление:

```bash
git pull && sudo docker compose up -d --build && ./scripts/prod_verify.sh
```

## Локально (инфра в Docker)

```bash
cp .env.example .env
docker compose --profile local up -d --build
```

## Документация

| Файл | О чём |
|------|--------|
| [YANDEX_PROD.md](YANDEX_PROD.md) | Прод-runbook (деплой / cron / .env) |
| [PROD_HANDOFF.md](PROD_HANDOFF.md) | Исторический handoff |
| [rule.md](rule.md) | ТЗ |

<!-- test sync marker: 2026-08-31T08:21:39Z -->
