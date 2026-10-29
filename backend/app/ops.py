"""Production plumbing: request IDs, JSON access logs, Prometheus metrics, rate limiting, config validation."""
import json, logging, os, sys, threading, time, uuid
from collections import defaultdict

from prometheus_client import Counter, Histogram, CONTENT_TYPE_LATEST, generate_latest

REQS = Counter("sealcheck_http_requests_total", "HTTP requests", ["method", "route", "status"])
LAT = Histogram("sealcheck_http_request_seconds", "HTTP latency", ["method", "route"])
RATE_LIMITED = Counter("sealcheck_rate_limited_total", "Requests rejected by rate limiter", ["bucket"])


class JsonFormatter(logging.Formatter):
    def format(self, r):
        d = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(r.created)) + "Z", "level": r.levelname,
             "logger": r.name, "msg": r.getMessage()}
        for k in ("request_id", "method", "path", "status", "ms", "ip", "user"):
            if hasattr(r, k):
                d[k] = getattr(r, k)
        if r.exc_info:
            d["exc"] = self.formatException(r.exc_info)
        return json.dumps(d)


def setup_logging():
    if os.environ.get("LOG_FORMAT", "json") != "json":
        return
    h = logging.StreamHandler(sys.stdout); h.setFormatter(JsonFormatter())
    root = logging.getLogger("sealcheck"); root.handlers = [h]; root.setLevel(os.environ.get("LOG_LEVEL", "INFO")); root.propagate = False


log = logging.getLogger("sealcheck.access")


class RateLimiter:
    """Fixed-window limiter. Uses Redis (INCR+EXPIRE) when REDIS_URL is set so limits hold across replicas,
    otherwise an in-process dict (single replica only)."""

    def __init__(self, redis_client=None):
        self.r = redis_client
        self.mem = defaultdict(lambda: [0, 0.0])
        self.lock = threading.Lock()

    def hit(self, key: str, limit: int, window_s: int) -> bool:
        if self.r is not None:
            try:
                k = f"rl:{key}:{int(time.time() // window_s)}"
                n = self.r.incr(k)
                if n == 1:
                    self.r.expire(k, window_s)
                return n <= limit
            except Exception:  # noqa: BLE001  Redis down: fail open, but locally limited below
                pass
        with self.lock:
            c = self.mem[key]
            t = time.time()
            if t - c[1] > window_s:
                c[0], c[1] = 0, t
            c[0] += 1
            return c[0] <= limit


RULES = [  # (path prefix, method, limit, window seconds)
    ("/api/auth/login", "POST", int(os.environ.get("RATE_LOGIN_PER_MIN", "10")), 60),
    ("/api/security/pii", "POST", 10, 60),
    ("/api/", "POST", int(os.environ.get("RATE_WRITE_PER_MIN", "120")), 60),
    ("/api/", "GET", int(os.environ.get("RATE_READ_PER_MIN", "1200")), 60),
]


def limiter_from_env():
    url = os.environ.get("REDIS_URL")
    if url:
        try:
            import redis
            return RateLimiter(redis.Redis.from_url(url, socket_timeout=1, socket_connect_timeout=1))
        except Exception:  # noqa: BLE001
            pass
    return RateLimiter()


def install(app, is_prod: bool):
    from fastapi import Request
    from fastapi.responses import JSONResponse, Response
    setup_logging()
    rl = limiter_from_env()
    app.state.rate_limiter = rl
    app.state.draining = False

    @app.middleware("http")
    async def ops_mw(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        if len(rid) > 64 or not rid.replace("-", "").isalnum():
            rid = uuid.uuid4().hex
        ip = request.client.host if request.client else "-"
        path, method = request.url.path, request.method
        if os.environ.get("RATE_LIMIT", "on") == "on":
            for prefix, m, limit, win in RULES:
                if path.startswith(prefix) and method == m:
                    if not rl.hit(f"{prefix}:{m}:{ip}", limit, win):
                        RATE_LIMITED.labels(prefix).inc()
                        return JSONResponse({"detail": "Too many requests"}, status_code=429,
                                            headers={"Retry-After": str(win), "X-Request-ID": rid})
                    break
        t0 = time.perf_counter()
        status = 500
        try:
            resp = await call_next(request)
            status = resp.status_code
        finally:
            dt = time.perf_counter() - t0
            route = getattr(request.scope.get("route"), "path", "unmatched")
            REQS.labels(method, route, str(status)).inc()
            LAT.labels(method, route).observe(dt)
            log.info("request", extra={"request_id": rid, "method": method, "path": path, "status": status,
                                       "ms": round(dt * 1000, 1), "ip": ip})
        resp.headers["X-Request-ID"] = rid
        resp.headers["Permissions-Policy"] = "camera=(), geolocation=(), microphone=(self)"
        resp.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        if is_prod:
            resp.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        return resp

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        return {"status": "ok"}

    @app.get("/readyz", include_in_schema=False)
    def readyz():
        from sqlalchemy import text
        from .db import engine
        checks = {}
        try:
            with engine.connect() as c:
                c.execute(text("SELECT 1"))
            checks["db"] = "ok"
        except Exception as e:  # noqa: BLE001
            checks["db"] = f"fail: {type(e).__name__}"
        if os.environ.get("QUEUE_BACKEND") == "rq" or os.environ.get("REDIS_URL"):
            try:
                from .queue_worker import redis_conn
                redis_conn().ping(); checks["redis"] = "ok"
            except Exception as e:  # noqa: BLE001
                checks["redis"] = f"fail: {type(e).__name__}"
        ok = all(v == "ok" for v in checks.values()) and not app.state.draining
        return JSONResponse({"ready": ok, "checks": checks, "draining": app.state.draining}, status_code=200 if ok else 503)

    @app.get("/metrics", include_in_schema=False)
    def metrics(request: Request):
        tok = os.environ.get("METRICS_TOKEN")
        if tok and request.headers.get("authorization") != f"Bearer {tok}":
            return JSONResponse({"detail": "forbidden"}, status_code=403)
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


class ConfigError(RuntimeError):
    pass


def validate_production_config(env: dict | None = None) -> list[str]:
    """Returns a list of problems. In ENV=production startup refuses to continue if any exist."""
    e = env if env is not None else os.environ
    p = []
    if len(e.get("SEALCHECK_JWT_SECRET", "")) < 32:
        p.append("SEALCHECK_JWT_SECRET must be set (>=32 chars)")
    if e.get("AUTH_MODE", "local") not in ("oidc", "google"):
        p.append("AUTH_MODE must be oidc or google (local demo login is disabled in production)")
    if e.get("AUTH_MODE") == "google" and not e.get("PUBLIC_BASE_URL", "").startswith(("https://", "http://localhost:", "http://127.0.0.1:")):
        p.append("PUBLIC_BASE_URL must be the https:// origin used in the Google redirect URI")
    if e.get("AUTH_MODE") == "oidc" and not e.get("OIDC_ISSUER"):
        p.append("OIDC_ISSUER must be set")
    db = e.get("DATABASE_URL") or e.get("SEALCHECK_DB_URL") or ""
    if not db.startswith(("postgres", "postgresql")):
        p.append("DATABASE_URL must point to PostgreSQL")
    if e.get("KMS_BACKEND", "soft") == "soft" and len(e.get("SEALCHECK_MASTER_KEY", "")) < 32:
        p.append("KMS_BACKEND must be aws|vault|pkcs11 or set SEALCHECK_MASTER_KEY (>=32 chars) for env-derived keys")
    if e.get("STORAGE_BACKEND", "fs") not in ("s3", "db"):
        p.append("STORAGE_BACKEND must be s3 or db (filesystem WORM is not tamper-proof or shared)")
    if e.get("SANDBOX_BACKEND", "auto") == "process" and e.get("SEALCHECK_ACCEPT_PROCESS_SANDBOX") != "1":
        p.append("SANDBOX_BACKEND=process is not isolated; use namespace or docker")
    if e.get("SEALCHECK_ALLOW_SEED") == "1":
        p.append("SEALCHECK_ALLOW_SEED must not be 1 in production")
    if "*" in e.get("CORS_ORIGINS", ""):
        p.append("CORS_ORIGINS must not contain *")
    if e.get("QUEUE_BACKEND", "thread") == "thread":  # inline (job runs inside the request) is allowed
        p.append("QUEUE_BACKEND should be rq or db (thread queue loses jobs on restart under multiple replicas)")
    return p


def fail_fast_if_insecure(is_prod: bool):
    if not is_prod:
        return
    probs = validate_production_config()
    if probs:
        raise ConfigError("Refusing to start in ENV=production:\n - " + "\n - ".join(probs))
