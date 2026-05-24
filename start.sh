#!/bin/bash
# Railway startup script.
# On first deploy: builds the SQLite DB from committed JSON files, then persists it to the volume.
# On subsequent deploys: the volume DB already exists, so just start the server.
set -e

VOLUME_DB="${DATABASE_PATH:-/data/second_brain.db}"
DATA_DIR=$(dirname "$VOLUME_DB")

mkdir -p "$DATA_DIR"

if [ ! -f "$VOLUME_DB" ]; then
    echo "First run — building database from JSON files..."
    DATABASE_PATH="$VOLUME_DB" python3 scripts/setup_db.py
    echo "Database ready at $VOLUME_DB"
else
    echo "Database exists at $VOLUME_DB"
fi

export DATABASE_PATH="$VOLUME_DB"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
