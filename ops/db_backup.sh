#!/usr/bin/env bash
# Logical backup of the SealCheck PostgreSQL database (custom format + SHA-256 sidecar).
# Usage: DATABASE_URL=postgresql://user@host:port/db ops/db_backup.sh [outdir]
# Restore: ops/db_restore.sh <file.dump>   (WORM object storage is backed up separately via bucket replication)
set -euo pipefail
# Use client tools matching the server major version (e.g. PG_BIN=/usr/lib/postgresql/16/bin)
[ -n "${PG_BIN:-}" ] && export PATH="$PG_BIN:$PATH"
: "${DATABASE_URL:?DATABASE_URL required}"
URL="${DATABASE_URL/postgresql+psycopg:/postgresql:}"
OUT="${1:-./backups}"; mkdir -p "$OUT"
F="$OUT/sealcheck-$(date -u +%Y%m%dT%H%M%SZ).dump"
pg_dump --format=custom --no-owner --no-privileges --dbname="$URL" --file="$F"
sha256sum "$F" > "$F.sha256"
echo "$F"
