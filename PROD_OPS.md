# ExplainLaw — прод-операции (ручной запуск)

Отдельная шпаргалка для операций на прод-хосте. Деплой и `.env` — в `YANDEX_PROD.md`, архитектура — в `PROD_HANDOFF.md`.

**Каталог на сервере:** `~/explain-law/regulatory-legal-acts` (или свой путь к репо)  
**Контейнер для CLI:** `regulatory-legal-acts-cron` (тот же образ и `.env`, что у daily cron)  
**Все команды ниже — через `make`** (внутри — `sudo docker exec` / `sudo docker compose`).

---

## 1. Быстрый старт

```bash
cd ~/explain-law/regulatory-legal-acts
git pull

make help          # все цели
make status        # backlog: pending_process, gate и т.д.
```

---

## 2. Make-цели

| Цель | Что делает |
|------|------------|
| `make build` | Пересобрать `app` + `cron`, перезапустить |
| `make up` / `make down` | Поднять / остановить compose |
| `make collect-all` | `collect --all` в фоне → `/app/logs/collect-all.log` |
| `make collect-logs` | `tail -f` журнала collect |
| `make collect-status` | Жив ли процесс collect |
| `make process` | `process --limit 500` в foreground (интерактив) |
| `make process-bg` | process в фоне → `/app/logs/process.log` |
| `make process-logs` | `tail -f` журнала process |
| `make process-status` | Жив ли process |
| `make gate` | `gate --limit 500` в foreground |
| `make gate-bg` | gate в фоне → `/app/logs/gate.log` |
| `make gate-logs` | `tail -f` журнала gate |
| `make gate-status` | Жив ли gate |
| `make pipeline-bg` | process → gate подряд в фоне |
| `make status` | `explainlaw status` (метрики БД) |

**Лимит по умолчанию:** `PROCESS_LIMIT=500`. Переопределение:

```bash
make process-bg PROCESS_LIMIT=50
make pipeline-bg PROCESS_LIMIT=1000
```

**Другой контейнер / путь к логу:**

```bash
make process-bg COLLECT_CONTAINER=regulatory-legal-acts-cron PROCESS_LOG=/app/logs/my-process.log
```

---

## 3. Типовые сценарии

### 3.1. Ежедневная работа (cron)

Cron в **08:00** сам запускает:

```
daily --process-limit 50 --fetch-missing 3
  → collect (окно вчера–сегодня)
  → process (макс. 50)
  → gate (макс. 50)
  → fetch-missing
```

Новые ФЗ с портала подхватываются автоматически. **Ручной запуск не нужен**, если backlog не раздули.

### 3.2. Полный сбор каталога (указы + постановления + ФЗ)

```bash
make collect-all
make collect-logs        # отдельный терминал
make collect-status
```

- Запись в `pipeline_run` появляется **только в конце** (может идти много часов).
- `collect --all` **не** запускает process — только метаданные + PDF в S3.

### 3.3. Догон необработанного backlog после collect

После `collect --all` в БД ~33k+ документов **без текста**. Cron обрабатывает **50/день** — для backfill мало.

**Рекомендуемый порядок:**

```bash
make process-bg
make process-logs        # ждём JSON со stats в конце порции

make gate-bg             # после завершения process
make gate-logs
```

Или одной командой:

```bash
make pipeline-bg
make process-logs
```

Повторять, пока `make status` не покажет приемлемый `pending_process`:

```bash
make status
```

**Не запускать** `explainlaw process` **без `--limit`** на полном backlog: долго молчит (грузит десятки тысяч кандидатов), первый вывод — через минуты.

### 3.4. Только свежие документы (range)

Без полного каталога:

```bash
sudo docker exec -it regulatory-legal-acts-cron \
  explainlaw collect --from 2025-01-01 --to 2026-09-02

make process-bg PROCESS_LIMIT=500
```

---

## 4. Collect vs process — в чём путаница

| Шаг | Команда | Результат |
|-----|---------|-----------|
| **Collect** | `collect`, `collect --all`, daily (первая фаза) | Запись в `npa_document`, PDF в S3 |
| **Process** | `process`, daily (вторая фаза) | PDF → `npa_text` → связи → дельта → `npa_summary` |
| **Gate** | `gate`, daily (третья фаза) | Проверка качества, `post_bank` |

**Cron не «только парсит новые»:** daily и **собирает** свежее, и **обрабатывает** любые необработанные из всей БД — но с лимитом 50.

---

## 5. Зачем `--limit` / `PROCESS_LIMIT`

| Без лимита | С лимитом (500) |
|------------|-----------------|
| ~33k документов за один прогон | Порция за десятки минут, виден прогресс в логе |
| Риск долгого зависания на старте | Удобно крутить в цикле |
| Пик на LLM / OCR / БД | Cron специально ставит 50, чтобы daily успел дойти до publish |

Для **ручного backfill** используйте `make process-bg` (limit=500 по умолчанию). Для **дайджеста ФЗ** backlog указы/постановлений можно не гонять — ~7.8k ФЗ уже с текстом.

---

## 6. Логи и диагностика

### Журналы make (внутри контейнера)

| Файл | Содержимое |
|------|------------|
| `/app/logs/collect-all.log` | `collect --all` |
| `/app/logs/process.log` | `process` |
| `/app/logs/gate.log` | `gate` |
| `/app/logs/cron.log` | supercronic (daily, publish, health) |

```bash
make process-logs
make gate-logs
sudo docker compose logs -f cron
```

### Процесс жив?

```bash
make process-status
make gate-status
make collect-status
```

### БД: последние collect/process

```bash
sudo docker exec -it regulatory-legal-acts-cron explainlaw status
```

Или SQL / `pipeline_run`: смотреть `started_at`, `metrics.new`, `metrics.candidates`.

### «Запустил process — тишина»

1. Без `--limit` — нормально молчит 1–5+ мин до первой строки.
2. Используйте **`make process-bg` + `make process-logs`**.
3. Предупреждение `fitz API is deprecated` — не ошибка (PyMuPDF).

### Убить зависший process

```bash
make process-status
sudo docker exec regulatory-legal-acts-cron pkill -f 'explainlaw process'   # если нужно
```

---

## 7. Эквивалент без make (если Makefile старый)

```bash
sudo docker exec -d regulatory-legal-acts-cron sh -c \
  'explainlaw process --limit 500 > /app/logs/process.log 2>&1'

sudo docker exec -t regulatory-legal-acts-cron tail -f /app/logs/process.log
```

---

## 8. Чеклист после `git pull`

```bash
git pull
make build              # если менялся код
make status
make process-bg         # при необходимости backfill
make process-logs
```
