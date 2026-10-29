#!/usr/bin/env bash
# Start the mock IdP + an OIDC-mode API (:8001) and a VISION_BACKEND=models API (:8002), capture extra shots, stop them.
set -euo pipefail; cd "$(dirname "$0")/.."; OUT="${1:-../screenshots}"; . .venv/bin/activate
python devtools/mock_oidc.py --port 9400 > /tmp/mock_oidc.log 2>&1 & M=$!
(cd backend && AUTH_MODE=oidc OIDC_ISSUER=http://127.0.0.1:9400 RATE_LIMIT=off uvicorn app.main:app --port 8001 > /tmp/api_oidc.log 2>&1) & O=$!
export SEALCHECK_DATA_DIR=/tmp/sealcheck_vision VISION_BACKEND=models; rm -rf $SEALCHECK_DATA_DIR
python seed/generate_samples.py > /dev/null; python seed/seed_db.py --force > /tmp/seed_vision.log 2>&1
(cd backend && RATE_LIMIT=off uvicorn app.main:app --port 8002 > /tmp/api_vision.log 2>&1) & V=$!
trap 'kill $M $O $V 2>/dev/null || true' EXIT
for port in 9400 8001 8002; do for i in $(seq 60); do curl -sf localhost:$port/ -o /dev/null && break; sleep 1; done; done
python scripts/screenshots_extra.py oidc "$OUT"; python scripts/screenshots_extra.py vision "$OUT"
