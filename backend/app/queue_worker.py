"""Out-of-process job workers.

QUEUE_BACKEND=rq : `python -m app.queue_worker rq`  (REDIS_URL, default redis://localhost:6379/0)
QUEUE_BACKEND=db : `python -m app.queue_worker db`  (polls the jobs table; on Postgres uses
                   SELECT ... FOR UPDATE SKIP LOCKED so several workers can run safely)
Tested here with fakeredis (RQ) and with SQLite/Postgres (DB claim). A real Redis server was not available.
"""
from __future__ import annotations
import os, signal, sys, time

_conn = None


def redis_conn():
    global _conn
    if _conn is None:
        import redis
        _conn = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
                                     socket_timeout=5, socket_connect_timeout=3)
    return _conn


def rq_queue(conn=None):
    from rq import Queue, Retry  # noqa: F401
    return Queue("sealcheck", connection=conn or redis_conn(), default_timeout=300)


def claim_next(session):
    """Atomically move one queued job to running. Returns its id or None."""
    from sqlalchemy import text
    from .db import IS_PG
    lock = " FOR UPDATE SKIP LOCKED" if IS_PG else ""
    row = session.execute(text(f"SELECT id FROM jobs WHERE status='queued' ORDER BY id LIMIT 1{lock}")).first()
    if not row:
        session.rollback()
        return None
    n = session.execute(text("UPDATE jobs SET status='running' WHERE id=:i AND status='queued'"), {"i": row[0]}).rowcount
    session.commit()
    return row[0] if n else None


_stop = False


def db_loop(poll_s: float = 1.0, once: bool = False):
    from .db import SessionLocal
    from .service import run_job_task
    while not _stop:
        with SessionLocal() as s:
            jid = claim_next(s)
        if jid:
            run_job_task(jid)
        elif once:
            return
        else:
            time.sleep(poll_s)
        if once:
            return


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("QUEUE_BACKEND", "db")

    def stop(*_):
        global _stop
        _stop = True
    signal.signal(signal.SIGTERM, stop); signal.signal(signal.SIGINT, stop)
    if mode == "rq":
        from rq import Worker
        Worker([rq_queue()], connection=redis_conn()).work(with_scheduler=False)
    else:
        db_loop()


if __name__ == "__main__":
    main()
