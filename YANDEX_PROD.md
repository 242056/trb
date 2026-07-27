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
- **app** — API на `:7000` (`explainlaw serve`)
- **cron** — supercronic: daily / weekly / backfill / health

Проверка:

```bash
sudo docker compose ps
curl -s http://127.0.0.1:7000/health
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

## 4. Расписание и прод-тест

Расписание собирается из env при старте `cron` (`docker/cron-entrypoint.sh`).

| Env | По умолчанию | Команда |
|-----|--------------|---------|
| `CRON_DAILY_SCHEDULE` | `0 8 * * *` | `explainlaw daily` |
| `CRON_WEEKLY_SCHEDULE` | `0 9 * * 1` | `daily --weekly-publish` (+ Telegram) |
| `CRON_BACKFILL_SCHEDULE` | `0 3 * * 0` | `rebuild-deltas --resume` |
| `CRON_HEALTH_SCHEDULE` | `0 10 * * *` | `health --alert` (1 раз/сутки) |

Telegram-алерты: `ALERT_TELEGRAM_MAX_PER_DAY=1` — не чаще одного сообщения в сутки, даже если health/daily дергают алерт несколько раз.

Лимиты парсинга: `PIPELINE_PROCESS_LIMIT`, `PIPELINE_FETCH_MISSING_LIMIT`, `PIPELINE_BACKFILL_LIMIT`, `PIPELINE_SMOKE_PROCESS_LIMIT`.

### Быстрый полный прогон на VPS/проде

VPS подходит как хост приложения, если `.env` указывает на Yandex PG + Kafka + S3 (не localhost).

```bash
# в .env на сервере:
cp .env.yandex.local .env   # или ваш прод-.env
# добавить:
CRON_RUN_ON_START=true
CRON_RUN_ON_START_JOB=smoke   # или weekly
PIPELINE_SMOKE_PROCESS_LIMIT=5
TZ=Europe/Moscow

sudo docker compose up -d --build
sudo docker compose logs -f cron
```

`smoke` = collect → process/gate (лимит) → fetch-missing → weekly publish → Telegram + запись в БД.

Разовый прогон без перезапуска cron:

```bash
sudo docker compose exec app explainlaw prod-smoke
# или полный weekly:
sudo docker compose exec app explainlaw daily --weekly-publish
```

После проверки выключите `CRON_RUN_ON_START=false`, иначе при каждом рестарте контейнера снова уйдёт дайджест.

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
| `docker/crontab` | fallback-расписание (абсолютные пути) |
| `docker/cron-entrypoint.sh` | генерация crontab из env + RUN_ON_START |
| `docker/render_crontab.py` | рендер crontab |

| `.env.example` | шаблон env |
| `rule.md` | ТЗ |
