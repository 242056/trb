#!/bin/sh
# Entrypoint для regulatory-legal-acts-cron:
# 1) генерирует crontab из env
# 2) опционально сразу прогоняет job (CRON_RUN_ON_START)
# 3) запускает supercronic
set -eu

export PATH="/usr/local/bin:${PATH}"
export TZ="${TZ:-${CRON_TIMEZONE:-Europe/Moscow}}"

CRONTAB_PATH="${CRONTAB_PATH:-/tmp/explainlaw.crontab}"
EXPLAINLAW_BIN="${EXPLAINLAW_BIN:-/usr/local/bin/explainlaw}"

echo "[cron] timezone=$TZ"
python /app/docker/render_crontab.py > "$CRONTAB_PATH"
echo "[cron] crontab:"
sed 's/^/  /' "$CRONTAB_PATH"

if [ ! -x /usr/local/bin/supercronic ]; then
  echo "[cron] FATAL: /usr/local/bin/supercronic missing or not executable" >&2
  exit 1
fi
if [ ! -x "$EXPLAINLAW_BIN" ]; then
  echo "[cron] FATAL: $EXPLAINLAW_BIN missing — rebuild image / check pip install" >&2
  exit 1
fi

run_on_start="$(echo "${CRON_RUN_ON_START:-false}" | tr '[:upper:]' '[:lower:]')"
if [ "$run_on_start" = "true" ] || [ "$run_on_start" = "1" ] || [ "$run_on_start" = "yes" ]; then
  job="$(echo "${CRON_RUN_ON_START_JOB:-weekly}" | tr '[:upper:]' '[:lower:]')"
  echo "[cron] RUN_ON_START job=$job"
  case "$job" in
    daily)
      "$EXPLAINLAW_BIN" daily
      ;;
    weekly)
      "$EXPLAINLAW_BIN" daily --weekly-publish
      ;;
    health)
      "$EXPLAINLAW_BIN" health --alert
      ;;
    smoke)
      "$EXPLAINLAW_BIN" prod-smoke
      ;;
    *)
      echo "[cron] unknown CRON_RUN_ON_START_JOB=$job (daily|weekly|health|smoke)" >&2
      exit 1
      ;;
  esac
  echo "[cron] RUN_ON_START finished ok"
fi

echo "[cron] starting supercronic"
exec /usr/local/bin/supercronic -passthrough-logs "$CRONTAB_PATH"
