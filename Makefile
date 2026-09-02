# ============================================================================
# ExplainLaw — прод-операции.
# Запускается на прод-сервере после `git pull` из main.
# ============================================================================

COLLECT_CONTAINER ?= regulatory-legal-acts-cron
COLLECT_LOG       ?= /app/logs/collect-all.log
PROCESS_LOG       ?= /app/logs/process.log
GATE_LOG          ?= /app/logs/gate.log
PROCESS_LIMIT     ?= 500

.PHONY: help build up down collect-all collect-logs collect-status \
        process process-bg process-logs process-status \
        gate gate-bg gate-logs gate-status \
        pipeline-bg status \
        test test-collect lint test-verbose

help: ## Список целей
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

build: ## Пересобрать app+cron и перезапустить
	sudo docker compose build app cron
	sudo docker compose up -d app cron

up: ## Поднять app+cron
	sudo docker compose up -d

down: ## Остановить
	sudo docker compose down

collect-all: ## Полный сбор каталога (--all) в фоне, лог в файл
	sudo docker exec -d $(COLLECT_CONTAINER) sh -c 'explainlaw collect --all > $(COLLECT_LOG) 2>&1'
	@echo "collect --all стартовал в фоне ($(COLLECT_CONTAINER))"
	@echo "журнал: make collect-logs | статус: make collect-status"

collect-logs: ## Следить за журналом collect (Ctrl+C — выйти)
	sudo docker exec -t $(COLLECT_CONTAINER) tail -f $(COLLECT_LOG)

collect-status: ## Процесс collect жив?
	sudo docker exec -t $(COLLECT_CONTAINER) sh -c 'ps aux | grep "[c]ollect" || echo "collect NOT running"'

process: ## Обработка PDF→текст→сводка (foreground, LIMIT=$(PROCESS_LIMIT))
	sudo docker exec -it $(COLLECT_CONTAINER) explainlaw process --limit $(PROCESS_LIMIT)

process-bg: ## process в фоне, лог в $(PROCESS_LOG)
	sudo docker exec -d $(COLLECT_CONTAINER) sh -c 'explainlaw process --limit $(PROCESS_LIMIT) > $(PROCESS_LOG) 2>&1'
	@echo "process стартовал в фоне ($(COLLECT_CONTAINER)), limit=$(PROCESS_LIMIT)"
	@echo "журнал: make process-logs | статус: make process-status"

process-logs: ## Следить за журналом process (Ctrl+C — выйти)
	sudo docker exec -t $(COLLECT_CONTAINER) sh -c 'touch $(PROCESS_LOG) && tail -f $(PROCESS_LOG)'

process-status: ## Процесс process жив?
	sudo docker exec -t $(COLLECT_CONTAINER) sh -c 'ps aux | grep "[e]xplainlaw process" || echo "process NOT running"'

gate: ## Гейты качества (foreground, LIMIT=$(PROCESS_LIMIT))
	sudo docker exec -it $(COLLECT_CONTAINER) explainlaw gate --limit $(PROCESS_LIMIT)

gate-bg: ## gate в фоне, лог в $(GATE_LOG)
	sudo docker exec -d $(COLLECT_CONTAINER) sh -c 'explainlaw gate --limit $(PROCESS_LIMIT) > $(GATE_LOG) 2>&1'
	@echo "gate стартовал в фоне ($(COLLECT_CONTAINER)), limit=$(PROCESS_LIMIT)"
	@echo "журнал: make gate-logs | статус: make gate-status"

gate-logs: ## Следить за журналом gate (Ctrl+C — выйти)
	sudo docker exec -t $(COLLECT_CONTAINER) sh -c 'touch $(GATE_LOG) && tail -f $(GATE_LOG)'

gate-status: ## Процесс gate жив?
	sudo docker exec -t $(COLLECT_CONTAINER) sh -c 'ps aux | grep "[e]xplainlaw gate" || echo "gate NOT running"'

pipeline-bg: ## process → gate в фоне (один sh, limit=$(PROCESS_LIMIT))
	sudo docker exec -d $(COLLECT_CONTAINER) sh -c 'explainlaw process --limit $(PROCESS_LIMIT) > $(PROCESS_LOG) 2>&1 && explainlaw gate --limit $(PROCESS_LIMIT) > $(GATE_LOG) 2>&1'
	@echo "pipeline process→gate стартовал в фоне, limit=$(PROCESS_LIMIT)"
	@echo "process: make process-logs | gate: make gate-logs"

status: ## Backlog: сколько документов без текста / в очереди
	sudo docker exec -it $(COLLECT_CONTAINER) explainlaw status

# ============================================================================
# Тесты (локально, ./.venv). Полный набор: 112 passed, 1 skipped.
# ============================================================================

VENV        ?= ./.venv
PYTEST      ?= $(VENV)/bin/python -m pytest
RUFF        ?= $(VENV)/bin/ruff
COLLECT_TESTS = tests/test_collect_window.py tests/test_collect_targets.py

test: ## Весь набор тестов (быстрый, ~17с)
	$(PYTEST) -q

test-verbose: ## Весь набор с именами кейсов и skip-причинами
	$(PYTEST) -v -rs

test-collect: ## Только collect-тесты (окно и цели)
	$(PYTEST) -q $(COLLECT_TESTS)

lint: ## Статический linter
	$(RUFF) check src tests
