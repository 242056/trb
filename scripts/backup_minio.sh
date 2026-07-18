#!/usr/bin/env bash
# Обёртка для backup_minio.py
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ -f .venv/bin/activate ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

export PYTHONPATH="${PYTHONPATH:-}:$ROOT/src"
mkdir -p backups/minio logs

python scripts/backup_minio.py "$@"
