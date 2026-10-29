run:
	./run.sh
reseed:
	RESEED=1 ./run.sh
test:
	.venv/bin/python -m pytest -q tests
smoke:
	.venv/bin/python scripts/smoke.py
screenshots:
	.venv/bin/python scripts/screenshots.py ../screenshots
build:
	cd frontend && npm ci && npm run build
.PHONY: run reseed test smoke screenshots build
