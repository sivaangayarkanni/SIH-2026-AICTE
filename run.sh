#!/usr/bin/env bash
# SealCheck one-command start: venv -> deps -> samples + seed -> frontend build -> API + UI on :8000
set -euo pipefail
cd "$(dirname "$0")"
PORT="${PORT:-8000}"
[ -f .env ] && set -a && . ./.env && set +a
# --- prerequisites (required: Python >= 3.11, Node >= 18; everything else optional with fallbacks) ---
PY="${PYTHON:-python3}"
$PY -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null || { echo "ERROR: Python >= 3.11 required (found: $($PY --version 2>&1)). Set PYTHON=/path/to/python3.11+"; exit 1; }
if [ ! -f frontend/dist/index.html ]; then
  command -v node >/dev/null || { echo "ERROR: Node.js >= 18 is required to build the UI (https://nodejs.org)"; exit 1; }
  node -e 'process.exit(+process.versions.node.split(".")[0] >= 18 ? 0 : 1)' || { echo "ERROR: Node >= 18 required (found $(node --version))"; exit 1; }
fi
command -v bwrap >/dev/null || echo "WARNING: bubblewrap not found -> sandbox falls back to 'process' mode (rlimits + Python socket guard; dev only). Linux: apt install bubblewrap"
command -v tesseract >/dev/null || echo "NOTE: tesseract not found -> OCR fallback disabled (only needed for scanned PDFs without a text layer)"
command -v clamscan >/dev/null || echo "NOTE: ClamAV not found -> heuristic malware scanner is used"
if [ ! -d .venv ]; then echo "Creating .venv and installing Python packages (first run: ~1-3 min)"; $PY -m venv .venv; fi
. .venv/bin/activate
python -c "import fastapi, pikepdf, pyhanko" 2>/dev/null || pip install -q -r requirements-dev.txt
DATA="${SEALCHECK_DATA_DIR:-backend/data}"
if [ ! -f "$DATA/sealcheck.db" ] || [ "${RESEED:-0}" = "1" ]; then
  python seed/generate_samples.py
  python seed/seed_db.py --force
fi
if [ ! -f frontend/dist/index.html ]; then (cd frontend && npm install --no-audit --no-fund && npm run build); fi
echo "SealCheck on http://localhost:$PORT  (API docs: /docs)"
cd backend && exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
