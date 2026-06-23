#!/usr/bin/env bash
# Minimal CI: prove migrations apply on a fresh SQLite DB, lint, and run the suite.
set -euo pipefail
cd "$(dirname "$0")/.."

PY=".venv/bin/python"
SCRATCH="data/_ci.db"
rm -f "$SCRATCH"

echo "==> alembic upgrade head (fresh sqlite)"
DATABASE_URL="sqlite:///./$SCRATCH" .venv/bin/alembic upgrade head

echo "==> ruff"
.venv/bin/ruff check src tests

echo "==> pytest"
$PY -m pytest -q

rm -f "$SCRATCH"
echo "OK"
