# ExplainLaw — деплой на прод-хост (Yandex)

Репозиторий: https://github.com/explain-law/regulatory-legal-acts  
Ветка для деплоя: **`main`**

На хосте только Docker (`app` + `cron`). PG / Kafka / Object Storage — в Yandex Cloud.

**Ручные операции** (collect / process / gate, make-цели, логи): **`PROD_OPS.md`**.

---

## 1. Один раз: поднять сервис

```bash
git clone https://github.com/explain-law/regulatory-legal-acts.git
cd regulatory-legal-acts
git checkout main
git pull

cp .env.example .env
# заполнить .env: DATABASE_URL, AWS_*, KAFKA_*, TELEGRAM_*  (см. §3)

# pip ходит на зеркало (pypi.org с VPS часто ReadTimeout)
sudo docker compose up -d --build
sudo docker compose exec app alembic upgrade head

# проверка
./scripts/prod_verify.sh
# или:
#   curl -s http://127.0.0.1:7000/health
#   sudo docker compose exec app explainlaw status
```

Подымаются:
- **app** — API `:7000`
- **cron** — supercronic: daily / weekly publish / backfill / health

Логи cron (не app):

```bash
sudo docker compose logs -f cron
sudo docker compose exec cron tail -f /app/logs/cron.log
```

Остановка: `sudo docker compose down` (данные в Yandex не трогает).

---

## 2. Обновление на уже работающем хосте

```bash
cd regulatory-legal-acts
git pull
sudo docker compose up -d --build
./scripts/prod_verify.sh
```

Миграции при необходимости: `sudo docker compose exec app alembic upgrade head`.

---

## 3. `.env` (минимум для прода)

Обязательно:

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
KAFKA_PIPELINE_EVENTS=false
LLM_TRANSPORT=kafka
QWEN_MODEL=qwen3:8b

OCR_ENABLED=true
OCR_ENGINE=tesseract

TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=-...
TELEGRAM_PUBLISH=true

PIPELINE_PROCESS_LIMIT=50
TZ=Europe/Moscow
CRON_RUN_ON_START=false
```

Важно:
- **Не** задавайте хостовый `KAFKA_SSL_CA_LOCATION` — CA уже в образе, compose выставляет путь внутри контейнера.
- `OCR_ENABLED=true` обязателен для сканов PDF (в образе tesseract + rus).
- `CRON_RUN_ON_START` держите `false`, иначе при каждом рестарте cron снова уйдёт job (smoke/weekly).

Полный список переменных — в `.env.example`.

---

## 4. Расписание (как должно быть после старта)

Генерируется при старте контейнера `cron` (`docker/cron-entrypoint.sh` → `cron-run.sh`).

| Когда (MSK) | Команда |
|-------------|---------|
| каждый день 08:00 | `daily --process-limit 50 --fetch-missing 3` (collect: вчера+сегодня) |
| каждый день 09:00 | `publish --mark-published` (сводка в Telegram; если новостей нет — тихий день) |
| каждый день 08:30 | ~~`health --alert`~~ **выкл.** (`CRON_HEALTH_ENABLED=false`) |
| вс 03:00 | `rebuild-deltas --resume --limit 500` |

Проверка crontab внутри контейнера:

```bash
sudo docker compose exec cron cat /tmp/explainlaw.crontab
```

В crontab **не должно** быть `--weekly-publish`. Weekly = только `publish`.

Сводка: заголовок вида `Обзор ФЗ · 7 августа 2026`. Если за день новых ФЗ нет — уходит «тихий день» (нормальный текст, не пустой список).  
OCR soft-wraps склеиваются при публикации.

---

## 5. Разовый smoke (опционально)

```bash
# в .env временно:
# CRON_RUN_ON_START=true
# CRON_RUN_ON_START_JOB=smoke
# PIPELINE_SMOKE_PROCESS_LIMIT=5
# затем: sudo docker compose up -d cron
# после проверки: CRON_RUN_ON_START=false и recreate cron

# или без рестарта cron:
sudo docker compose exec app explainlaw prod-smoke
sudo docker compose exec app explainlaw publish --mark-published   # только дайджест
```

---

## 6. Чеклист

- [ ] `main` актуален (`git pull`)
- [ ] `.env` с Yandex PG / S3 / Kafka / Telegram
- [ ] `OCR_ENABLED=true`, `OCR_ENGINE=tesseract`
- [ ] `PIPELINE_PROCESS_LIMIT=50`, `CRON_RUN_ON_START=false`
- [ ] `docker compose up -d --build` → app + cron Up
- [ ] `alembic upgrade head`
- [ ] `./scripts/prod_verify.sh` → OK
- [ ] Qwen-worker слушает Kafka `llm.requests` / `llm.responses`
- [ ] Бот в TG-группе; каждый день 09:00 — сводка (или тихий день)

---

## 7. Файлы

| Файл | Назначение |
|------|------------|
| `Dockerfile` | образ (tesseract, supercronic, Yandex CA) |
| `docker-compose.yml` | app + cron |
| `docker/cron-entrypoint.sh` | crontab из env + RUN_ON_START |
| `docker/cron-run.sh` | START/OK/FAIL → stdout + `/app/logs/cron.log` |
| `docker/crontab` | fallback (должен совпадать с render) |
| `.env.example` | шаблон |
| `scripts/prod_verify.sh` | проверка после деплоя |
| `rule.md` | ТЗ |
