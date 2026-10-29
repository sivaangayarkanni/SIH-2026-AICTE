#!/usr/bin/env bash
# Restore a dump produced by ops/db_backup.sh into DATABASE_URL (target DB must exist; pgvector must be installed).
# Verifies the SHA-256 sidecar first. Destructive: existing objects are dropped (--clean).
set -euo pipefail
# Use client tools matching the server major version (e.g. PG_BIN=/usr/lib/postgresql/16/bin)
[ -n "${PG_BIN:-}" ] && export PATH="$PG_BIN:$PATH"
: "${DATABASE_URL:?DATABASE_URL required}"; F="${1:?dump file required}"
URL="${DATABASE_URL/postgresql+psycopg:/postgresql:}"
sha256sum -c "$F.sha256"
psql "$URL" -qc "CREATE EXTENSION IF NOT EXISTS vector"
pg_restore --clean --if-exists --no-owner --no-privileges --exit-on-error --dbname="$URL" "$F"
echo "restored $F"
