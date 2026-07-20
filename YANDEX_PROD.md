# ExplainLaw — инструкция для прода (Yandex)

Репозиторий: https://github.com/explain-law/regulatory-legal-acts  
ТЗ: `rule.md`.

---

## 1. Архитектура

| Компонент | Где |
|-----------|-----|
| **Приложение** (`app` + `cron`) | Docker на хосте |
| PostgreSQL | Yandex Managed PG (снаружи) |
| Kafka / Qwen | Yandex Managed Kafka (снаружи) |
| PDF | Yandex Object Storage `explain-npa` (снаружи) |
| Telegram | алерты + еженедельный дайджест |

Postgres/MinIO/Kafka **внутри Docker только для локалки** (`--profile local`). На проде их не поднимаем.

---

## 2. Прод: запуск всего сервиса через Docker

```bash
git clone https://github.com/explain-law/regulatory-legal-acts.git
cd regulatory-legal-acts
git checkout main

cp .env.example .env
# заполнить Yandex PG / Kafka / AWS_* / Telegram — см. §3

sudo docker compose up -d --build
```

Поднятся:
- **app** — API на `:8000` (`explainlaw serve`)
- **cron** — supercronic: daily / weekly / backfill / health

Проверка:

```bash
sudo docker compose ps
curl -s http://127.0.0.1:8000/health
sudo docker compose exec app explainlaw status
sudo docker compose logs -f cron
```

Миграции (один раз):

```bash
sudo docker compose exec app alembic upgrade head
```

Остановка: `sudo docker compose down` (данные Yandex не трогает).

---

## 3. `.env` (прод)

```bash
DATABASE_URL=postgresql+psycopg://USER:PASS@HOST:6432/DB
DATABASE_SSLMODE=require

AWS_ENDPOINT_URL=https://storage.yandexcloud.net
AWS_KEY_ID=...
AWS_SECRET_KEY=...
AWS_BUCKET=explain-npa

KAFKA_BOOTSTRAP_SERVERS=rc1a-....mdb.yandexcloud.net:9091
KAFKA_USERNAME=llm
KAFKA_PASSWORD=...
KAFKA_SECURITY_PROTOCOL=SASL_SSL
KAFKA_SASL_MECHANISM=SCRAM-SHA-512
KAFKA_SSL_CA_LOCATION=/certs/YandexCA.crt
KAFKA_ENABLED=true
KAFKA_PIPELINE_EVENTS=false
LLM_TRANSPORT=kafka
QWEN_MODEL=qwen3:8b

OCR_ENABLED=true
OCR_ENGINE=tesseract

TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=-...
TELEGRAM_PUBLISH=true
```

CA Kafka: положите сертификат в `./certs` и раскомментируйте volume в `docker-compose.yml`.

---

## 4. Расписание (`docker/crontab`)

| Когда | Команда |
|-------|---------|
| 08:00 ежедневно | `explainlaw daily` |
| 09:00 пн | `explainlaw daily --weekly-publish` (+ Telegram) |
| 03:00 вс | `rebuild-deltas --resume --limit 500` |
| */6 ч :30 | `explainlaw health --alert` |

---

## 5. OCR / модели

- OCR в образе: **tesseract** (+ rus). Старые тексты в БД при обычном process не переOCR’ятся.
- Расшифровка норм: **Qwen3 8B** через Kafka.
- Gateway — опционально для публичных сводок.

---

## 6. Локально (инфра + app)

```bash
docker compose --profile local up -d --build
```

В `.env` для сети compose используйте хосты `postgres`, `minio`, `kafka`.

---

## 7. Чеклист

- [ ] `.env` с Yandex / AWS / Telegram  
- [ ] `docker compose up -d --build` → app + cron  
- [ ] `alembic upgrade head`  
- [ ] Qwen-worker на Kafka  
- [ ] Бот в TG-группе  
- [ ] `docker compose exec app explainlaw status`  

---

## 8. Файлы

| Файл | Назначение |
|------|------------|
| `Dockerfile` | образ |
| `docker-compose.yml` | app + cron (+ local infra) |
| `docker/crontab` | расписание |
| `.env.example` | шаблон env |
| `rule.md` | ТЗ |
