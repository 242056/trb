# ExplainLaw — отчёт о работе и передача на прод

**Версия:** 0.2.0  
**Дата:** 2026-07-18  
**ТЗ:** `rule.md` (Шаг 0 + Шаг 1)  
**Репозиторий:** `trb` / пакет `explainlaw`  
**Прод-инфра:** см. `YANDEX_PROD.md` (VPS выведен; Yandex PG + Kafka + MinIO)

---

## 1. Резюме

ExplainLaw — конвейер ежедневного сбора федеральных законов с `publication.pravo.gov.ru`, извлечения текста из PDF (включая TIFF-ZIP → PDF), построения дельт изменений, ИИ-сводок, двух гейтов качества и еженедельной публикации из «банка готовых карточек».

**Код подготовлен к проду без VPS:** Yandex Managed PG/Kafka, OCR (paddle/tesseract/yandex), TIFF-ZIP, `rebuild-deltas --resume`, алерты (webhook/Telegram/jsonl), экспорт дайджеста с `source_url`, cron `*_prod.sh`.

**Операционные блокеры при переносе:**
1. Пересоздать MinIO / восстановить PDF-бэкап (старый VPS недоступен).
2. Подключить Qwen через Kafka (`LLM_TRANSPORT=kafka`) и Gateway для сводок.
3. Выставить cron: `./scripts/install-cron.sh --prod`.

---

## 2. Проделанная работа

### 2.1. Инфраструктура

| Компонент | Реализация |
|-----------|------------|
| PostgreSQL 16 | `docker-compose.yml`, Alembic миграции `001`, `002` |
| MinIO (S3) | Бакеты `npa-raw`, `npa-snapshots`, ~7590 PDF |
| Kafka 3.8 | 7 топиков, producer на всех шагах CLI |
| Инициализация | `scripts/init_infra.py` — миграции + бакеты + топики |

### 2.2. Конвейер обработки

```
collect → process → gate → fetch-missing → [publish]
   │         │        │          │
   ▼         ▼        ▼          ▼
npa_document  npa_text  gate_flag  missing_acts_queue
npa_raw       npa_summary post_bank
(MinIO)       npa_delta
              norm_change_event
              npa_relation / npa_enactment
              npa_sector / act_group_id
```

**Команды CLI** (`explainlaw`):

| Команда | Назначение |
|---------|------------|
| `collect` | Сбор ФЗ из API (daily / range / `--all`) |
| `list` | Список документов в БД |
| `process` | PDF → текст → связи → events → дельта → сводка |
| `gate` | Гейты №1 и №2 → `post_bank` |
| `fetch-missing` | Подтягивание актов из очереди недостающих |
| `rebuild-deltas` | Пересборка дельт поправок + гейты |
| `publish` | Еженедельный дайджест из `post_bank` |
| `daily` | Полный ежедневный конвейер |
| `health` | Здоровье + алерты |
| `status` | Метрики заполнения БД |
| `serve` | FastAPI веб-интерфейс (:8000) |

### 2.3. Ключевые модули

| Модуль | Путь | § ТЗ |
|--------|------|------|
| Сбор | `collector/service.py` | 3, 4 |
| PDF/текст | `extraction/pdf_extractor.py` | 3.4 |
| Изменения | `extraction/changes.py`, `norms/event_writer.py` | 6.4, 8.3 |
| Дельта | `delta/builder.py` | 8.3 |
| Сводки | `llm/gateway.py` | 8.1 |
| Гейты | `gates/delta_gate.py`, `gates/summary_gate.py` | 9 |
| Публикация | `content/publisher.py`, `content/selector.py` | 7.2 |
| Секторы | `content/sectors.py` | 4.3, 5.5 |
| Группы актов | `content/act_groups.py` | 4.4 |
| Kafka | `messaging/kafka.py` | 8.2 |
| Наблюдаемость | `observability/health.py`, `recorder.py` | 11 |

### 2.4. Kafka-топики

| Топик | Когда публикуется |
|-------|-------------------|
| `npa.document.discovered` | Новый документ в каталоге |
| `npa.raw.stored` | PDF сохранён в MinIO |
| `npa.text.extracted` | Текст извлечён из PDF |
| `npa.delta.computed` | Дельта собрана |
| `npa.summary.generated` | Сводка создана |
| `npa.gate.result` | Гейт завершён |
| `npa.post.ready` | Карточка в post_bank / публикация |

Consumers не реализованы — на Шаге 1 достаточно producer (буфер событий для будущих подписчиков).

### 2.5. Исправления в ходе разработки

- **process:** приоритет документов без текста; commit после каждого документа.
- **fetch-missing:** нормализация пробелов в названиях; сохранение метаданных при отсутствии PDF.
- **post_bank:** исправлен `MultipleResultsFound` при digest + single.
- **rebuild-deltas:** режим `rebuild_deltas_only` (без повторного PDF/OCR).
- **processor:** savepoint — старая дельта не удаляется, если новая не собралась.
- **Kafka:** producer подключён во все CLI-команды и `DailyPipeline`.

### 2.6. Cron и скрипты

| Скрипт | Назначение |
|--------|------------|
| `scripts/daily.sh` | Ежедневный конвейер + docker up + init |
| `scripts/backfill.sh` | rebuild-deltas → fetch-missing → status |
| `scripts/install-cron.sh` | Установка crontab |

Расписание по умолчанию:
- **08:00 ежедневно** — `daily.sh`
- **09:00 понедельник** — `daily.sh --weekly-publish`
- **03:00 воскресенье** — `backfill.sh` (LIMIT=500)

### 2.7. Тесты

```bash
python -m pytest tests/ -q   # 12 passed
```

---

## 3. Управление продуктом

### 3.1. Соответствие ТЗ (§11)

| Критерий | Статус | Комментарий |
|----------|--------|-------------|
| Ежедневный сбор + дедуп | ✅ | 7761 ФЗ в БД |
| PDF → текст | ✅ | 7590 / 7761 |
| Дельта + статус полноты | ⚠️ | 5 дельт; нужен Qwen |
| Очередь недостающих актов | ✅ | 615 записей |
| ИИ-маршрутизация Qwen/Gateway | ⚠️ | Код есть, модели не подключены |
| Оба гейта | ✅ | 4 passed, 7576 flagged |
| Еженедельный контент из банка | ✅ | publish + fallback-форматы |
| Наблюдаемость | ✅ | health, status, pipeline_run |
| MinIO + Postgres | ✅ | |
| norm_change_event | ⚠️ | 254 события / 93 док. |
| Kafka | ✅ | producer |
| npa_sector + act_group | ✅ | 4008 док. / 7590 групп |

### 3.2. Текущие метрики БД (на 2026-07-01)

```json
{
  "in_database": 7761,
  "with_text": 7590,
  "with_summary": 7590,
  "with_delta": 5,
  "with_sectors": 4570,
  "with_act_group": 7590,
  "missing_acts_queue": 615,
  "gate_passed": 4,
  "gate_flagged": 7576,
  "post_bank_ready": 10,
  "pending_process": 171
}
```

**Расшифровка:**
- **171 pending** — нет PDF на портале (не заполнимо).
- **7487 флагов `no_delta`** — нет дельты → гейт нечего проверять.
- **213 `summary_date_not_grounded`** — артефакт механических сводок без Gateway.
- **Все 7590 сводок** — `model_route=qwen` (механический fallback, не настоящий Qwen).

### 3.3. Операционная модель

**Ритмы (§7.1):**
- Сбор — ежедневно (`daily` / cron 08:00).
- Публикация — еженедельно (cron пн 09:00 с `--weekly-publish`).
- Бэкфилл дельт — еженедельно (cron вс 03:00) или вручную после деплоя Qwen.

**Буфер и банк (§7.2):**
- `post_bank` — готовые карточки после гейтов.
- `publish` выбирает 3–7 лучших; при нехватке — fallback «вступает в силу на неделе».
- Резерв: 10 ready-карточек в банке.

**Алерты:**
- `explainlaw health --alert` + `ALERT_WEBHOOK_URL`.
- Тихий сбой сбора: `COLLECT_SILENT_ALERT_HOURS=36`.

### 3.4. Что можно заполнить без моделей

| Действие | Команда | Эффект |
|----------|---------|--------|
| Cron | `./scripts/install-cron.sh` | Автоматизация |
| Ежедневный цикл | `explainlaw daily` | Новые ФЗ → process → gate |
| Missing acts | `explainlaw fetch-missing --limit 20` | Подтягивание целевых актов |
| Публикация | `explainlaw publish` | Дайджест из 10 ready |
| Секторы (keyword) | уже прогонялись | ~53% документов |

### 3.5. Что требует моделей

| Модель | Где | Без неё |
|--------|-----|---------|
| **Qwen3 8B** | `norms/event_writer.py` | ~0.06% дельт (regex) |
| **Gateway** | `llm/gateway.py` | Механические excerpt-сводки |
| **Gateway** | `gates/summary_gate.py` | Семантический гейт №2 пропускается |
| OCR (опц.) | `extraction/pdf_extractor.py` | Сканы без текста |

---

## 4. Схема данных (связи)

### 4.1. Основной граф

```
npa_document (1) ──< npa_raw          → MinIO: npa-raw/{eo_number}/...
              ├──< npa_text (1:1)
              ├──< npa_summary
              ├──< npa_delta (0..1)
              ├──< npa_enactment
              ├──< npa_relation ──> npa_document (target)
              ├──< npa_sector ──> sector_dict
              ├──< gate_flag
              └──  act_group_id (UUID)

npa_document ──< norm_change_event ──> norm
missing_acts_queue (очередь внешних актов)
post_bank ──< post_item
pipeline_run (журнал запусков)
```

### 4.2. DBeaver / подключение к БД

| Параметр | Значение (локально / docker) |
|----------|------------------------------|
| Host | `localhost` (на проде — IP сервера) |
| Port | `5432` |
| Database | `explainlaw` |
| User | `explainlaw` |
| Password | `explainlaw` (на проде — сменить!) |
| JDBC URL | `jdbc:postgresql://localhost:5432/explainlaw` |
| SQLAlchemy | `postgresql+psycopg://explainlaw:explainlaw@localhost:5432/explainlaw` |

**Полезные запросы:**

```sql
-- Сводка заполнения
SELECT
  (SELECT count(*) FROM npa_document) AS docs,
  (SELECT count(*) FROM npa_text) AS texts,
  (SELECT count(*) FROM npa_delta) AS deltas,
  (SELECT count(*) FROM post_bank WHERE status = 'ready') AS post_ready;

-- Поправки без дельты
SELECT d.eo_number, d.name, d.publish_date_short
FROM npa_document d
JOIN npa_text t ON t.document_id = d.id
LEFT JOIN npa_delta dd ON dd.document_id = d.id
WHERE d.name ILIKE '%внесении изменен%'
  AND dd.id IS NULL
LIMIT 20;

-- Очередь недостающих актов
SELECT status, count(*) FROM missing_acts_queue GROUP BY status;

-- Последние запуски конвейера
SELECT job_type, status, started_at, metrics
FROM pipeline_run ORDER BY started_at DESC LIMIT 10;
```

### 4.3. MinIO

| Параметр | Значение |
|----------|----------|
| Endpoint | `localhost:9000` |
| Console | `http://localhost:9001` |
| Access Key | `explainlaw` |
| Secret Key | `explainlawsecret` |
| Бакет сырья | `npa-raw` |
| Путь в БД | `npa_raw.storage_path` = `npa-raw/{eo_number}/file.pdf` |

---

## 5. Передача на прод: пошаговая инструкция

### 5.1. Требования к серверу

- **ОС:** Linux (Ubuntu 22.04+ рекомендуется) или macOS.
- **RAM:** ≥ 8 GB (Docker: Postgres + MinIO + Kafka).
- **Диск:** ≥ 50 GB (PDF ~7590 файлов + БД ~2–5 GB).
- **Docker** + **Docker Compose** v2.
- **Python** 3.11+.
- **Сеть:** исходящий доступ к `publication.pravo.gov.ru`.
- **Отдельно (домашний GPU-сервер):** Qwen3 8B через OpenAI-compatible API.
- **Облако:** Gateway API key (OpenAI / совместимый провайдер).

### 5.2. Развёртывание с нуля (без переноса данных)

```bash
# 1. Клонировать репозиторий
git clone <repo-url> /opt/explainlaw
cd /opt/explainlaw

# 2. Виртуальное окружение
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 3. Конфигурация
cp .env.example .env
# Отредактировать .env — см. раздел 5.4

# 4. Инфраструктура
docker compose up -d
python scripts/init_infra.py

# 5. Первичный сбор каталога (долго, ~30–60 мин)
explainlaw collect --all

# 6. Обработка (долго, часы)
explainlaw process

# 7. Проверка
explainlaw status
explainlaw health

# 8. Cron
chmod +x scripts/*.sh
./scripts/install-cron.sh

# 9. Веб (опционально)
explainlaw serve --host 0.0.0.0 --port 8000
```

### 5.3. Перенос существующей БД и MinIO (с dev-машины на прод)

#### A. PostgreSQL — дамп и восстановление

**На исходной машине (dev):**

```bash
cd /path/to/trb
docker compose up -d postgres

# Полный дамп (схема + данные)
docker compose exec -T postgres pg_dump -U explainlaw -d explainlaw -Fc \
  > explainlaw_backup_$(date +%Y%m%d).dump

# Или plain SQL
docker compose exec -T postgres pg_dump -U explainlaw -d explainlaw \
  > explainlaw_backup_$(date +%Y%m%d).sql
```

**На прод-сервере:**

```bash
cd /opt/explainlaw
docker compose up -d postgres
# Дождаться healthy

# Восстановление из custom format
docker compose exec -T postgres pg_restore -U explainlaw -d explainlaw --clean --if-exists \
  < explainlaw_backup_YYYYMMDD.dump

# Или из SQL
docker compose exec -T postgres psql -U explainlaw -d explainlaw \
  < explainlaw_backup_YYYYMMDD.sql

# Проверка
docker compose exec postgres psql -U explainlaw -d explainlaw \
  -c "SELECT count(*) FROM npa_document;"
```

#### B. MinIO — перенос PDF

**Вариант 1: mc mirror (рекомендуется)**

```bash
# Установить mc: https://min.io/docs/minio/linux/reference/minio-mc.html

# Исходный сервер
mc alias set dev http://localhost:9000 explainlaw explainlawsecret
mc mirror dev/npa-raw ./npa-raw-export/
mc mirror dev/npa-snapshots ./npa-snapshots-export/  # если есть

# Прод-сервер (после docker compose up)
mc alias set prod http://localhost:9000 explainlaw <PROD_SECRET>
mc mb --ignore-existing prod/npa-raw
mc mirror ./npa-raw-export/ prod/npa-raw/
```

**Вариант 2: копирование Docker volume**

```bash
# На dev
docker run --rm -v trb_minio_data:/data -v $(pwd):/backup alpine \
  tar czf /backup/minio_data.tar.gz -C /data .

# Перенести minio_data.tar.gz на прод, затем:
docker compose up -d minio
docker run --rm -v trb_minio_data:/data -v $(pwd):/backup alpine \
  tar xzf /backup/minio_data.tar.gz -C /data
```

**Важно:** пути в `npa_raw.storage_path` (`npa-raw/...`) должны совпадать с объектами в MinIO. После переноса проверить:

```bash
explainlaw process --limit 1   # не должно падать на get_by_path
```

#### C. Kafka

События в Kafka **не персистентны для бизнес-логики** — все данные в Postgres + MinIO. На проде достаточно:

```bash
python scripts/init_infra.py   # создаст топики
```

Перенос offset/topic data не требуется.

#### D. Файлы проекта (без данных)

Переносятся через git:

```bash
git clone / push → pull на проде
pip install -e ".[dev]"
cp .env.example .env   # и заполнить прод-значения
```

**Не коммитить:** `.env`, `logs/`, `*.dump`, `.venv/`.

### 5.4. Конфигурация `.env` на проде

```env
# === ОБЯЗАТЕЛЬНО СМЕНИТЬ ПАРОЛИ ===
DATABASE_URL=postgresql+psycopg://explainlaw:<STRONG_PASSWORD>@localhost:5432/explainlaw
MINIO_ACCESS_KEY=explainlaw
MINIO_SECRET_KEY=<STRONG_MINIO_SECRET>
MINIO_ENDPOINT=localhost:9000
MINIO_BUCKET_RAW=npa-raw
MINIO_BUCKET_SNAPSHOTS=npa-snapshots
MINIO_SECURE=false

KAFKA_BOOTSTRAP_SERVERS=localhost:9092
KAFKA_ENABLED=true

# === LLM (критично для дельт и контента) ===
QWEN_API_BASE=http://<home-gpu-server>:8000/v1
QWEN_API_KEY=<key>
QWEN_MODEL=qwen3-8b

GATEWAY_API_BASE=https://api.openai.com/v1
GATEWAY_API_KEY=sk-...
GATEWAY_MODEL=gpt-4o-mini

# === Наблюдаемость ===
ALERT_WEBHOOK_URL=https://hooks.slack.com/...   # или Telegram, PagerDuty
COLLECT_SILENT_ALERT_HOURS=36

OCR_ENABLED=false
PRAVO_API_BASE_URL=http://publication.pravo.gov.ru
PRAVO_BLOCK_PRESIDENT=president
PRAVO_DOCUMENT_TYPE_FZ_ID=82a8bf1c-3bc7-47ed-827f-7affd43a7f27
```

**Docker Compose на проде** — обновить пароли Postgres в `docker-compose.yml` и синхронизировать с `DATABASE_URL`.

**Kafka на проде** — если приложение и Kafka на разных хостах, изменить:
```yaml
KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://<prod-ip>:9092
```
и в `.env`: `KAFKA_BOOTSTRAP_SERVERS=<prod-ip>:9092`.

### 5.5. После переноса — обязательные проверки

```bash
docker compose ps                    # все healthy
python scripts/init_infra.py        # миграции + бакеты + топики
explainlaw health                   # healthy: true
explainlaw status                   # in_database ≈ 7761, with_text ≈ 7590

# Smoke-test конвейера
explainlaw collect                  # new: 0+ (зависит от дня)
explainlaw process --limit 3
explainlaw gate --limit 3
explainlaw fetch-missing --limit 3
```

### 5.6. Запуск после подключения Qwen + Gateway

```bash
# 1. Пересборка дельт (6572 поправки, ~15–30 мин без GPU, дольше с Qwen)
explainlaw rebuild-deltas

# 2. Гейты на поправках с дельтой
explainlaw gate --force --amendments-only

# 3. Пересводки через Gateway (опционально, долго)
explainlaw process --force --amendments-only --limit 100

# 4. Публикация
explainlaw publish

# 5. Cron
./scripts/install-cron.sh
```

### 5.7. Резервное копирование на проде

Рекомендуемый cron бэкапа (добавить вручную):

```bash
# Ежедневно 02:00 — дамп Postgres
0 2 * * * docker compose -f /opt/explainlaw/docker-compose.yml exec -T postgres \
  pg_dump -U explainlaw -Fc explainlaw > /backup/explainlaw_$(date +\%Y\%m\%d).dump

# Еженедельно — mirror MinIO
0 3 * * 0 mc mirror prod/npa-raw /backup/minio/npa-raw/
```

### 5.8. Мониторинг

| Что | Как |
|-----|-----|
| Здоровье | `explainlaw health` / `GET /health` |
| Метрики БД | `explainlaw status` |
| Журнал запусков | `SELECT * FROM pipeline_run ORDER BY started_at DESC` |
| Логи cron | `/var/log/explainlaw-daily.log` или `$ROOT/logs/` |
| MinIO console | `http://<host>:9001` |
| Веб-UI | `explainlaw serve` → `http://<host>:8000` |

---

## 6. Структура репозитория

```
trb/
├── rule.md                 # Техническое задание
├── PROD_HANDOFF.md         # Этот документ
├── docker-compose.yml      # Postgres, MinIO, Kafka
├── .env.example            # Шаблон конфигурации
├── pyproject.toml          # Зависимости, explainlaw CLI
├── alembic/                # Миграции БД
├── scripts/
│   ├── init_infra.py       # Миграции + MinIO + Kafka topics
│   ├── daily.sh            # Ежедневный cron
│   ├── backfill.sh         # Бэкфилл дельт
│   └── install-cron.sh     # Установка crontab
├── src/explainlaw/         # Исходный код
└── tests/                  # 12 тестов
```

---

## 7. Известные ограничения и риски

| Риск | Описание | Митигация |
|------|----------|-----------|
| Нет Qwen | 99% поправок без дельты | Деплой Qwen + `rebuild-deltas` |
| Нет Gateway | Механические сводки, слабый гейт №2 | Подключить Gateway API |
| 171 no_pdf | PDF нет на портале | Не блокер; мониторить API |
| Потеря дельт при rebuild | Был баг (исправлен savepoint) | Повторить rebuild после Qwen |
| Kafka в daily collect | `DailyCollector` в `daily.py` без kafka_producer | Не критично; collect через CLI публикует |
| Consumers | Нет подписчиков Kafka | Достаточно для Шага 1 |
| Разметка релевантности §7.2 | Не реализована | Следующая итерация |

---

## 8. Контакты и передача

**Что передать команде эксплуатации:**
1. Этот файл (`PROD_HANDOFF.md`).
2. ТЗ (`rule.md`).
3. Дамп БД + архив MinIO (или доступ к dev-серверу для экспорта).
4. `.env` с прод-секретами (через secure channel, не git).
5. Доступ к GPU-серверу Qwen и Gateway API key.

**Критерий успешной передачи:**
```bash
explainlaw health          # healthy: true
explainlaw status          # in_database > 7000, with_text > 7000
docker compose ps          # all running
crontab -l | grep ExplainLaw
```

После подключения моделей:
```bash
explainlaw rebuild-deltas
explainlaw status          # with_delta >> 5
explainlaw publish         # digest_created: true
```

---

*Документ сгенерирован по состоянию кодовой базы и БД на 2026-07-01.*
