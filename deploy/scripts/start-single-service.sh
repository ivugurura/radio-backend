#!/usr/bin/env bash
set -euo pipefail

CURRENT_USER="$(whoami)"
APP_ROOT="${APP_ROOT:-/home/$CURRENT_USER/radio/api}"
VENV_DIR="${VENV_DIR:-$APP_ROOT/.venv}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-7080}"
GUNICORN_WORKERS="${GUNICORN_WORKERS:-2}"
CELERY_CONCURRENCY="${CELERY_CONCURRENCY:-2}"

cd "$APP_ROOT"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

if [ -f "$VENV_DIR/bin/activate" ]; then
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
else
  echo "Virtual environment not found at $VENV_DIR" >&2
  exit 1
fi

cleanup() {
  local exit_code=$?
  if [ -n "${gunicorn_pid:-}" ]; then
    kill "$gunicorn_pid" 2>/dev/null || true
    wait "$gunicorn_pid" 2>/dev/null || true
  fi
  if [ -n "${celery_pid:-}" ]; then
    kill "$celery_pid" 2>/dev/null || true
    wait "$celery_pid" 2>/dev/null || true
  fi
  exit "$exit_code"
}

trap cleanup EXIT INT TERM

"$VENV_DIR/bin/gunicorn" config.wsgi:application \
  --bind "$HOST:$PORT" \
  --workers "$GUNICORN_WORKERS" &

gunicorn_pid=$!

"$VENV_DIR/bin/celery" -A config.celery worker -l info --concurrency "$CELERY_CONCURRENCY" &
celery_pid=$!

wait -n "$gunicorn_pid" "$celery_pid"

kill "$gunicorn_pid" "$celery_pid" 2>/dev/null || true
wait "$gunicorn_pid" "$celery_pid" 2>/dev/null || true
