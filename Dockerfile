# syntax=docker/dockerfile:1.7
# UNTESTED: Docker is not available on the build box. The image has never been built.
FROM node:20-slim AS ui
WORKDIR /ui
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS deps
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /venv
COPY backend/requirements.txt /tmp/requirements.txt
RUN /venv/bin/pip install -r /tmp/requirements.txt

FROM python:3.12-slim AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends bubblewrap tesseract-ocr libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 10001 sealcheck && useradd -u 10001 -g sealcheck -d /app -s /usr/sbin/nologin sealcheck
COPY --from=deps /venv /venv
WORKDIR /app
COPY --chown=root:root backend/ backend/
COPY --chown=root:root seed/ seed/
COPY --from=ui --chown=root:root /ui/dist frontend/dist
ENV PATH=/venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000 SEALCHECK_DATA_DIR=/data ENV=production
RUN mkdir /data && chown sealcheck:sealcheck /data
USER 10001:10001
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request,sys;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz').status==200 else 1)"
WORKDIR /app/backend
# migrations run as a separate job (see compose 'migrate' / k8s Job); seeding is refused in production
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*' --timeout-graceful-shutdown 30"]
