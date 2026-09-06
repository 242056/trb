# Второй сервер: process/gate в ту же БД

**Хост воркера:** `80.78.244.91`  
Прод (`app` + `cron`) остаётся как есть: collect, daily 50, publish в Telegram.

Этот хост **только** обрабатывает backlog (`process` → `gate`) и пишет в **ту же** Yandex Postgres / S3 / Kafka.

Параллель: **2 контейнера** `worker-0` / `worker-1`, шард `document.id % 2`.

Файлы (локально, не в git, если не попросите иначе):

- `docker-compose.worker.yml` — два шарда
- `docker/worker-entrypoint.sh`
- `.env.worker.example` → на сервере копируете в `.env.worker`

---

## Характеристики сервера

GPU **не нужна** — LLM ходит в Kafka (Qwen на другом хосте). Здесь CPU OCR (Tesseract) + PDF + сеть.

| | Минимум | Нормально для ~32k backlog |
|--|---------|----------------------------|
| **vCPU** | 4 | **8** |
| **RAM** | 8 GB | **16 GB** |
| **Диск** | 40 GB SSD | **80 GB** SSD (логи, слой образа, tmp PDF) |
| **Сеть** | исходящий интернет | стабильный канал к Yandex Cloud + `publication.pravo.gov.ru` |
| **ОС** | Ubuntu 22.04/24.04 x86_64 | то же + Docker |

Почему так:

- порция process — до **500** документов в RAM (метаданные + PDF с S3);
- Tesseract на многостраничных PDF грузит CPU;
- без GPU: узкое место — CPU OCR и latency LLM, не видеокарта.

Не берите 2 vCPU / 4 GB — Docker + Python + Tesseract + пачка PDF легко упрутся в OOM (как `process` без лимита).

В Yandex Cloud / security group **whitelist `80.78.244.91/32`**:

1. Managed PostgreSQL (порт **6432**)
2. Object Storage (HTTPS)
3. Managed Kafka (**9091**)

Иначе коннект к БД будет `Operation not permitted` / timeout.

---

## Запуск на втором сервере

```bash
git clone https://github.com/explain-law/regulatory-legal-acts.git
cd regulatory-legal-acts
git checkout main
git pull

# файлы worker положить в репо (скопировать с машины, где они созданы)
cp .env.worker.example .env.worker
# вписать DATABASE_URL, AWS_*, KAFKA_* как на проде

chmod +x docker/worker-entrypoint.sh
sudo docker compose -f docker-compose.worker.yml --env-file .env.worker up -d --build

sudo docker compose -f docker-compose.worker.yml logs -f worker-0 worker-1
# или
sudo docker exec -t regulatory-legal-acts-worker-0 tail -f /app/logs/worker-0.log
sudo docker exec -t regulatory-legal-acts-worker-1 tail -f /app/logs/worker-1.log
```

Остановка:

```bash
sudo docker compose -f docker-compose.worker.yml down
```

---

## Что не делать на этом хосте

- не запускать `collect` / `daily` / `publish` — дубли и гонки с прод-cron;
- не включать `TELEGRAM_PUBLISH`;
- не поднимать второй `cron` с тем же crontab.

Прод-cron по утрам по-прежнему process **50** — это нормально: daily без шарда может пересечься с воркером на одних id, второй просто skip/уже обработано.

`KAFKA_LLM_GROUP_ID` в примере — `explainlaw-llm-worker`; каждый LLM-запрос и так берёт уникальную consumer group по `correlation_id`.
