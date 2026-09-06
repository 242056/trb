#!/bin/sh
# Drain process + gate backlog. Same DB as prod. No collect / publish.
# Optional sharding: WORKER_SHARD_COUNT + WORKER_SHARD_INDEX (document.id % count).
set -eu

LIMIT="${WORKER_PROCESS_LIMIT:-100}"
SLEEP="${WORKER_LOOP_SLEEP:-15}"
LOG="${WORKER_LOG:-/app/logs/worker.log}"
SHARD_COUNT="${WORKER_SHARD_COUNT:-1}"
SHARD_INDEX="${WORKER_SHARD_INDEX:-0}"
mkdir -p "$(dirname "$LOG")" /app/logs/published

ts() { date '+%Y-%m-%d %H:%M:%S%z'; }

SHARD_ARGS=""
if [ "$SHARD_COUNT" -gt 1 ]; then
  SHARD_ARGS="--shard-count ${SHARD_COUNT} --shard-index ${SHARD_INDEX}"
fi

echo "[$(ts)] worker start limit=${LIMIT} sleep=${SLEEP}s shard=${SHARD_INDEX}/${SHARD_COUNT}" | tee -a "$LOG"

while true; do
  echo "[$(ts)] START explainlaw process --limit ${LIMIT} ${SHARD_ARGS}" | tee -a "$LOG"
  set +e
  # shellcheck disable=SC2086
  explainlaw process --limit "${LIMIT}" ${SHARD_ARGS} >>"$LOG" 2>&1
  pec=$?
  set -e
  echo "[$(ts)] process exit=${pec}" | tee -a "$LOG"

  echo "[$(ts)] START explainlaw gate --limit ${LIMIT} ${SHARD_ARGS}" | tee -a "$LOG"
  set +e
  # shellcheck disable=SC2086
  explainlaw gate --limit "${LIMIT}" ${SHARD_ARGS} >>"$LOG" 2>&1
  gec=$?
  set -e
  echo "[$(ts)] gate exit=${gec}" | tee -a "$LOG"

  sleep "${SLEEP}"
done
