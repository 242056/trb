# ExplainLaw — инструкция для прода (Yandex)

Репозиторий: https://github.com/explain-law/regulatory-legal-acts  
ТЗ: `rule.md`. Локальная отладка с Docker — в конце документа.

---

## 1. Архитектура на проде

| Компонент | Где | Docker? |
|-----------|-----|---------|
| Код / cron / CLI `explainlaw` | Хост (Python 3.11+) | **Нет** |
| PostgreSQL | Yandex Managed PG | Нет |
| Kafka (Qwen) | Yandex Managed Kafka | Нет |
| PDF / сырьё | Yandex Object Storage, бакет `explain-npa` | Нет |
| Qwen worker | Отдельный сервер, топики `llm.requests` → `llm.responses` | Нет |
| Gateway (опц.) | Облачный OpenAI-совместимый API | Нет |
| Telegram | Бот в группе: алерты + еженедельный дайджест | Нет |

`docker compose up` на проде **ничего не делает** (`no service selected`).  
Postgres/MinIO/Kafka в compose только за profile `local` (для ноутбука).

---

## 2. Первый запуск на сервере

```bash
git clone https://github.com/explain-law/regulatory-legal-acts.git
cd regulatory-legal-acts
git checkout main   # или актуальная ветка

python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,ocr]"
# если нужен PaddleOCR:
# pip install -e ".[paddle]"

cp .env.example .env
# заполнить .env — см. §3

# миграции (только PG; Kafka/S3 уже в облаке)
alembic upgrade head

explainlaw status
explainlaw health
```

Cron:

```bash
chmod +x scripts/*_prod.sh scripts/backup_minio.sh scripts/install-cron.sh
./scripts/install-cron.sh --prod
# посмотреть без установки: ./scripts/install-cron.sh --prod --print
```

---

## 3. `.env` (прод)

Минимум:

```bash
# PostgreSQL (Yandex)
DATABASE_URL=postgresql+psycopg://USER:PASS@HOST:6432/DB
DATABASE_SSLMODE=require

# Object Storage (Yandex S3)
AWS_ENDPOINT_URL=https://storage.yandexcloud.net
AWS_KEY_ID=...
AWS_SECRET_KEY=...
AWS_BUCKET=explain-npa

# Kafka (Yandex) + Qwen
KAFKA_BOOTSTRAP_SERVERS=rc1a-....mdb.yandexcloud.net:9091
KAFKA_USERNAME=llm
KAFKA_PASSWORD=...
KAFKA_SECURITY_PROTOCOL=SASL_SSL
KAFKA_SASL_MECHANISM=SCRAM-SHA-512
KAFKA_SSL_CA_LOCATION=/path/to/YandexInternalRootCA.crt
KAFKA_ENABLED=true
KAFKA_PIPELINE_EVENTS=false
LLM_TRANSPORT=kafka
KAFKA_LLM_REQUESTS_TOPIC=llm.requests
KAFKA_LLM_RESPONSES_TOPIC=llm.responses
KAFKA_LLM_GROUP_ID=explainlaw-llm
QWEN_MODEL=qwen3:8b

# OCR для НОВЫХ сканов (старые с текстом в БД не переOCR’ятся в обычном process)
OCR_ENABLED=true
OCR_ENGINE=paddle
OCR_TEXT_THRESHOLD=200

# Telegram
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=-...
TELEGRAM_PUBLISH=true

# Опционально: публичные сводки
# GATEWAY_API_BASE=...
# GATEWAY_API_KEY=...
# GATEWAY_MODEL=gpt-4o-mini

COLLECT_SILENT_ALERT_HOURS=36
PUBLISH_EXPORT_DIR=logs/published
ALERT_LOG_PATH=logs/alerts.jsonl
```

Секреты в git **не** класть. Образец полей: `.env.example`.

---

## 4. Что уже развёрнуто (состояние на момент передачи)

- Yandex PG: каталог ФЗ, тексты, дельты, post_bank  
- S3 `explain-npa`: ~7590 PDF; пути в `npa_raw` вида `explain-npa/{eo}.pdf`  
- ~171 документов без PDF в S3 (на портале часто нет файла) — не блокер  
- Расшифровка норм: **Qwen3 8B** через Kafka  
- OCR по умолчанию в старых `.env` мог быть `false` — для новых сканов включить `true`

---

## 5. Ежедневная / недельная работа

| Когда | Скрипт | Что делает |
|-------|--------|------------|
| Каждый день 08:00 | `scripts/daily_prod.sh` | collect → process → gate → fetch-missing → health |
| Понедельник 09:00 | `scripts/daily_prod.sh --weekly-publish` | то же + дайджест, export в `logs/published`, **пост в Telegram** |
| Вс 03:00 | `scripts/backfill_prod.sh` | догон PDF / deltas `--resume` |
| Каждые 6 ч | `scripts/health_prod.sh` | health + алерты в TG при проблемах |
| Вс 02:00 | `scripts/backup_minio.sh` | бэкап бакета Object Storage |

Ручные команды:

```bash
explainlaw status
explainlaw health --alert
explainlaw daily
explainlaw daily --weekly-publish
explainlaw publish --mark-published          # дайджест в файл + Telegram
explainlaw collect --days 3
explainlaw process --limit 50
explainlaw rebuild-deltas --resume --limit 200
explainlaw backfill-pdfs --limit 100
```

### Telegram: формат дайджеста

```
Дайджест ФЗ (дд.мм–дд.мм.гггг)

1. №…-ФЗ — название
Текст карточки…
🔗 Источник   ← ссылка на pravo.gov.ru
```

Нужно: бот добавлен в группу и может писать.  
Алерты: `⚠️ ExplainLaw` + текст проблемы (тихий сбор и т.п.).

---

## 6. OCR — кратко

| Ситуация | Поведение |
|----------|-----------|
| `OCR_ENABLED=false` | Новые сканы без текстового слоя → плохой/пустой текст |
| `OCR_ENABLED=true` | OCR только если в PDF мало текста; уже заполненный `npa_text` в обычном process **не** трогается |
| Движок | `OCR_ENGINE=paddle` (запас: `tesseract`, `yandex`) |

Массовый догон OCR: `RUN_OCR=1 ./scripts/backfill_prod.sh` или `python scripts/ocr_backfill.py`.

---

## 7. LLM / модели

| Задача | Модель | Как |
|--------|--------|-----|
| Дельты / norm events («расшифровка») | Qwen3 8B | Kafka `llm.requests` / `llm.responses` |
| Публичная сводка | Gateway (если задан) иначе Qwen/механический fallback | HTTP |
| Гейт №2 semantic | Gateway → иначе Qwen | после механики |

Без живого Qwen-worker дельты строятся regex-fallback’ом (хуже полнота).

---

## 8. Чеклист «прод жив»

- [ ] `.env` на хосте, `explainlaw status` отвечает  
- [ ] `docker compose up` → `no service selected` (ожидаемо)  
- [ ] Cron `--prod` установлен (`crontab -l`)  
- [ ] `OCR_ENABLED=true` (для новых сканов)  
- [ ] Qwen-worker слушает Kafka  
- [ ] Бот в Telegram-группе, `publish --mark-published` или weekly отрабатывает  
- [ ] CA для Kafka лежит по `KAFKA_SSL_CA_LOCATION`  
- [ ] Gateway (по желанию) для «лица» сводок  

---

## 9. Локальная разработка (не прод)

```bash
cp .env.example .env          # localhost Postgres/MinIO/Kafka
docker compose --profile local up -d
pip install -e ".[dev]"
python scripts/init_infra.py
explainlaw daily
```

---

## 10. Связанные файлы

| Файл | Назначение |
|------|------------|
| `YANDEX_PROD.md` | этот runbook |
| `.env.example` | шаблон переменных |
| `scripts/daily_prod.sh` | дневной cron без Docker |
| `scripts/install-cron.sh --prod` | установка crontab |
| `PROD_HANDOFF.md` | исторический handoff / перенос данных |
| `rule.md` | ТЗ |
