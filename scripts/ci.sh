#!/usr/bin/env bash
# Minimal CI: prove migrations apply on a fresh SQLite DB, lint, and run the suite
# (worker + dashboard API), then type-check/build the frontend if Node is available.
set -euo pipefail
cd "$(dirname "$0")/.."

PY=".venv/bin/python"
SCRATCH="data/_ci.db"
rm -f "$SCRATCH"

echo "==> install (editable, with api + dev extras)"
.venv/bin/pip install -e ".[api,dev]" -q

echo "==> alembic upgrade head (fresh sqlite)"
DATABASE_URL="sqlite:///./$SCRATCH" .venv/bin/alembic upgrade head

echo "==> ruff (worker + api + personal/storage/bot packages + tests)"
.venv/bin/ruff check src tests

echo "==> pytest (worker + dashboard API + personal/board/attachments/control + bot + integration)"
$PY -m pytest -q

rm -f "$SCRATCH"

# Frontend gate (skipped if Node/npm absent so the Python CI still runs standalone).
if command -v npm >/dev/null 2>&1 && [ -d frontend/node_modules ]; then
  echo "==> frontend lint + unit tests + build"
  ( cd frontend && npm run lint && npm test && npm run build )
else
  echo "==> frontend build skipped (npm or frontend/node_modules not present)"
fi

echo "OK"
