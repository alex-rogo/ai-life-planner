#!/bin/sh
set -eu

if [ -z "${WORKSPACE_ROOT:-}" ]; then
  python -m alembic upgrade head
  if [ "${SEED_ON_START:-false}" = "true" ]; then
    python -m app.seed
  fi
else
  python -c 'from app.config import get_settings; from app.workspaces import warm_demo; warm_demo(get_settings())'
fi

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
