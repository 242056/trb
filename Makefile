# ============================================================================
# ExplainLaw — прод-операции.
# Запускается на прод-сервере после `git pull` из main.
# ============================================================================

COLLECT_CONTAINER ?= regulatory-legal-acts-cron
COLLECT_LOG       ?= /app/logs/collect-all.log

.PHONY: help build up down collect-all collect-logs collect-status \
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
