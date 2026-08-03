#!/bin/sh
# Быстрая проверка после docker compose up на прод-хосте.
set -eu

COMPOSE="${COMPOSE:-docker compose}"
# shellcheck disable=SC2086
if ! $COMPOSE ps >/dev/null 2>&1; then
  COMPOSE="sudo docker compose"
fi

echo "== compose =="
$COMPOSE ps

echo "== app /health =="
curl -fsS http://127.0.0.1:7000/health
echo

echo "== status =="
$COMPOSE exec -T app explainlaw status

echo "== cron crontab =="
$COMPOSE exec -T cron sh -c 'cat /tmp/explainlaw.crontab'

echo "== cron expectations =="
ct="$($COMPOSE exec -T cron sh -c 'cat /tmp/explainlaw.crontab')"
echo "$ct" | grep -q 'daily --process-limit' || {
  echo "FAIL: daily без --process-limit" >&2
  exit 1
}
echo "$ct" | grep -q 'publish --mark-published' || {
  echo "FAIL: weekly не publish --mark-published" >&2
  exit 1
}
echo "$ct" | grep -q -- '--weekly-publish' && {
  echo "FAIL: старый --weekly-publish всё ещё в crontab" >&2
  exit 1
}
$COMPOSE exec -T cron test -x /app/docker/cron-run.sh
$COMPOSE exec -T cron test -x /app/docker/cron-entrypoint.sh

echo "== cron.log (last 30) =="
$COMPOSE exec -T cron sh -c 'tail -n 30 /app/logs/cron.log 2>/dev/null || echo "(пусто — дождитесь первого job)"'

echo "OK: prod verify passed"
