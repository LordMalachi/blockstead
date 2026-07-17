#!/bin/sh
set -eu

: "${BLOCKSTEAD_BIND_HOST:=0.0.0.0}"
: "${BLOCKSTEAD_PORT:=8765}"
: "${BLOCKSTEAD_DATA_DIR:=/var/lib/blockstead}"
: "${BLOCKSTEAD_SERVER_ROOT:=/srv/minecraft}"
: "${BLOCKSTEAD_STATIC_DIR:=/opt/blockstead/frontend/dist}"

export BLOCKSTEAD_BIND_HOST
export BLOCKSTEAD_PORT
export BLOCKSTEAD_DATA_DIR
export BLOCKSTEAD_SERVER_ROOT
export BLOCKSTEAD_STATIC_DIR

python -m blockstead.database_migrations \
    --database "${BLOCKSTEAD_DATA_DIR}/blockstead.db" \
    --config /opt/blockstead/backend/alembic.ini \
    --migrations /opt/blockstead/backend/migrations

exec python -m uvicorn blockstead.app:app \
    --host "${BLOCKSTEAD_BIND_HOST}" \
    --port "${BLOCKSTEAD_PORT}"

