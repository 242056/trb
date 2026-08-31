# ============================================================================
# ExplainLaw — прод-операции.
# Запускается на прод-сервере после `git pull` из main.
# ============================================================================

COLLECT_CONTAINER ?= regulatory-legal-acts-cron
COLLECT_LOG       ?= /app/logs/collect-all.log

.PHONY: help build up down collect-all collect-logs collect-status

help: ## Список целей
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

build: ## Пересобрать app+cron и перезапустить
	docker compose build app cron
	docker compose up -d app cron

up: ## Поднять app+cron
	docker compose up -d

down: ## Остановить
	docker compose down

collect-all: ## Полный сбор каталога (--all) в фоне, лог в файл
	docker exec -d $(COLLECT_CONTAINER) sh -c 'explainlaw collect --all > $(COLLECT_LOG) 2>&1'
	@echo "collect --all стартовал в фоне ($(COLLECT_CONTAINER))"
	@echo "журнал: make collect-logs | статус: make collect-status"

collect-logs: ## Следить за журналом collect (Ctrl+C — выйти)
	docker exec -t $(COLLECT_CONTAINER) tail -f $(COLLECT_LOG)

collect-status: ## Процесс collect жив?
	docker exec -t $(COLLECT_CONTAINER) sh -c 'ps aux | grep "[c]ollect" || echo "collect NOT running"'
