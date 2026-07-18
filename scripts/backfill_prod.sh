#!/usr/bin/env bash
# Прод-догон: PDF → OCR (опц.) → rebuild-deltas --resume → fetch-missing
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ -f .venv/bin/activate ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

export PYTHONPATH="${PYTHONPATH:-}:$ROOT/src"
mkdir -p logs

LIMIT="${LIMIT:-200}"
PDF_LIMIT="${PDF_LIMIT:-$LIMIT}"
FETCH_MISSING_LIMIT="${FETCH_MISSING_LIMIT:-20}"

echo "[backfill_prod] backfill-pdfs --limit $PDF_LIMIT"
explainlaw backfill-pdfs --limit "$PDF_LIMIT"

if [ "${RUN_OCR:-0}" = "1" ]; then
  echo "[backfill_prod] ocr_backfill"
  python scripts/ocr_backfill.py --limit "${OCR_LIMIT:-$LIMIT}"
fi

echo "[backfill_prod] rebuild-deltas --resume --limit $LIMIT"
explainlaw rebuild-deltas --resume --limit "$LIMIT"

echo "[backfill_prod] fetch-missing --limit $FETCH_MISSING_LIMIT"
explainlaw fetch-missing --limit "$FETCH_MISSING_LIMIT"

explainlaw status
