"""SQLAlchemy data layer.

Production: PostgreSQL 15+ with pgvector (DATABASE_URL=postgresql+psycopg://...), schema managed by Alembic
(backend/migrations). Dev/tests: SQLite (default), schema via create_all, vectors stored as JSON arrays.
Schema: separate PII vault, immutable document versions, append-only hash-chained audit log (DB trigger on
Postgres), job queue, evidence store, photo/document embeddings (pgvector HNSW indexes on Postgres)."""
from datetime import datetime, timezone
from sqlalchemy import (create_engine, Column, Integer, String, Text, DateTime, Float, ForeignKey, Boolean, JSON, event, LargeBinary,
                        CheckConstraint, Index, UniqueConstraint, text)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, backref
from sqlalchemy.types import TypeDecorator
from .config import DB_URL, DB_POOL_SIZE, DB_MAX_OVERFLOW, DB_POOL_TIMEOUT_S, DB_STATEMENT_TIMEOUT_MS

IS_PG = DB_URL.startswith("postgresql")
EMBED_DIM = 384  # DINOv2-small CLS dim; text embeddings use the same width

if IS_PG:
    engine = create_engine(DB_URL, pool_size=DB_POOL_SIZE, max_overflow=DB_MAX_OVERFLOW, pool_timeout=DB_POOL_TIMEOUT_S,
                           pool_pre_ping=True, pool_recycle=1800,
                           connect_args={"application_name": "sealcheck"})

    @event.listens_for(engine, "connect")
    def _pg_session_settings(dbapi_conn, _rec):
        # Set per connection instead of the libpq "options" startup parameter, which PgBouncer-style
        # poolers (e.g. Neon's -pooler endpoint) reject.
        with dbapi_conn.cursor() as cur:
            cur.execute(f"SET statement_timeout = {int(DB_STATEMENT_TIMEOUT_MS)}")
        dbapi_conn.commit()
else:
    engine = create_engine(DB_URL, connect_args={"check_same_thread": False})


class Embedding(TypeDecorator):
    """pgvector `vector(n)` on PostgreSQL; JSON list on SQLite (dev). Python value: list[float] | None."""
    impl = JSON
    cache_ok = True

    def __init__(self, dim=EMBED_DIM):
        super().__init__()
        self.dim = dim

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector
            return dialect.type_descriptor(Vector(self.dim))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        v = [float(x) for x in value]
        if len(v) != self.dim:
            raise ValueError(f"embedding must have {self.dim} dims, got {len(v)}")
        return v

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return [float(x) for x in value]


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _):
    if not IS_PG:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
Base = declarative_base()


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class College(Base):
    __tablename__ = "colleges"
    id = Column(Integer, primary_key=True)
    code = Column(String(20), unique=True, nullable=False)
    name = Column(String(200), nullable=False)
    city = Column(String(80))
    state = Column(String(80))
    lat = Column(Float)
    lon = Column(Float)
    institution_type = Column(String(80))


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String(200), unique=True, nullable=False)
    name = Column(String(120), nullable=False)
    title = Column(String(120))
    role = Column(String(20), nullable=False)  # college | officer | senior_officer | admin | pending (signed up, no access yet)
    college_id = Column(Integer, ForeignKey("colleges.id"), nullable=True)
    password_hash = Column(String(300), nullable=False)
    avatar_seed = Column(String(60))
    college = relationship("College")
    __table_args__ = (CheckConstraint("role in ('college','officer','senior_officer','admin','pending')", name="ck_users_role"),)


class Application(Base):
    __tablename__ = "applications"
    id = Column(Integer, primary_key=True)
    ref = Column(String(40), unique=True)
    college_id = Column(Integer, ForeignKey("colleges.id"), nullable=False)
    category = Column(String(60), nullable=False)
    title = Column(String(200))
    academic_year = Column(String(20), default="2026-27")
    status = Column(String(40), default="Draft")
    risk_score = Column(Integer, default=0)
    deadline = Column(DateTime)
    created_at = Column(DateTime, default=now)
    submitted_at = Column(DateTime)
    decision = Column(String(40))
    decision_reason = Column(Text)
    decision_by = Column(Integer, ForeignKey("users.id"))
    decided_at = Column(DateTime)
    guidance_json = Column(JSON)
    college = relationship("College")
    documents = relationship("Document", back_populates="application", cascade="all,delete")
    __table_args__ = (Index("ix_applications_status", "status"), Index("ix_applications_college", "college_id"),
                      CheckConstraint("risk_score between 0 and 100", name="ck_app_risk"))


class Document(Base):
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=False)
    doc_type = Column(String(60), nullable=False)
    filename = Column(String(255))
    mime = Column(String(60))
    size = Column(Integer)
    sha256 = Column(String(64))
    status = Column(String(40), default="Verification Pending")
    risk_score = Column(Integer, default=0)
    lab_type = Column(String(20))
    analysis_json = Column(JSON)
    text_embedding = Column(Embedding())  # visible-text embedding (feature-hashing, see pipeline/textembed.py)
    created_at = Column(DateTime, default=now)
    application = relationship("Application", back_populates="documents")
    __table_args__ = (Index("ix_documents_app", "application_id"), Index("ix_documents_sha", "sha256"),
                      CheckConstraint("risk_score between 0 and 100", name="ck_doc_risk"))
    versions = relationship("DocumentVersion", cascade="all,delete")


class DocumentVersion(Base):
    """Immutable original file record (write-once). Never updated after insert."""
    __tablename__ = "document_versions"
    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    version_no = Column(Integer, default=1)
    sha256 = Column(String(64), nullable=False)
    stored_path = Column(String(400), nullable=False)
    sanitized_path = Column(String(400))
    size = Column(Integer)
    created_at = Column(DateTime, default=now)
    __table_args__ = (UniqueConstraint("document_id", "version_no", name="uq_docver"),)


class DocumentMetadata(Base):
    __tablename__ = "document_metadata"
    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    key = Column(String(80))
    value = Column(Text)


class PiiVault(Base):
    """Separate PII vault. Values are envelope-encrypted (AES-256-GCM DEK wrapped by KMS KEK).
    blind_index = HMAC(PAN) so cross-college matching works without decrypting."""
    __tablename__ = "pii_vault"
    id = Column(Integer, primary_key=True)
    college_id = Column(Integer, ForeignKey("colleges.id"))
    document_id = Column(Integer, ForeignKey("documents.id"))
    kind = Column(String(20))  # PAN | AADHAAR
    ciphertext = Column(Text)
    wrapped_dek = Column(Text)
    nonce = Column(Text)
    key_id = Column(String(40))
    blind_index = Column(String(64), index=True)
    masked = Column(String(40))
    created_at = Column(DateTime, default=now)


class Job(Base):
    __tablename__ = "jobs"
    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    status = Column(String(20), default="queued")  # queued|running|done|failed
    stage = Column(String(40))
    progress_json = Column(JSON, default=list)
    token_jti = Column(String(40))
    token_exp = Column(Integer)
    attempts = Column(Integer, default=0)
    error = Column(Text)
    created_at = Column(DateTime, default=now)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    duration_ms = Column(Integer)
    __table_args__ = (Index("ix_jobs_status", "status"),
                      CheckConstraint("status in ('queued','running','done','failed')", name="ck_jobs_status"))


class Evidence(Base):
    __tablename__ = "evidence"
    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    module = Column(String(10))  # 4A 4B 4C 4D 5
    rule_id = Column(String(40))
    clause = Column(String(200))
    severity = Column(String(10))  # info|low|medium|high|critical
    outcome = Column(String(10))   # pass|fail|warn
    title = Column(String(200))
    detail = Column(Text)
    page = Column(Integer)
    bbox_json = Column(JSON)
    created_at = Column(DateTime, default=now)


class PhotoIndex(Base):
    __tablename__ = "photo_index"
    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("documents.id"))
    college_id = Column(Integer, ForeignKey("colleges.id"))
    phash = Column(String(32))
    path = Column(String(400))
    lat = Column(Float)
    lon = Column(Float)
    lab_type = Column(String(20))
    embedding = Column(Embedding())   # DINOv2-small global descriptor (VISION_BACKEND=models)
    layout_hash = Column(String(64))  # room-structure layout hash
    __table_args__ = (Index("ix_photo_college", "college_id"),)


class AuditLog(Base):
    """Append-only, hash-linked. hash = SHA256(prev_hash || canonical_json(entry))."""
    __tablename__ = "audit_log"
    id = Column(Integer, primary_key=True)
    ts = Column(String(40), nullable=False)
    actor = Column(String(200))
    role = Column(String(20))
    action = Column(String(80))
    target = Column(String(120))
    ip = Column(String(60))
    details = Column(Text)
    prev_hash = Column(String(64))
    hash = Column(String(64), unique=True)


class Override(Base):
    __tablename__ = "overrides"
    id = Column(Integer, primary_key=True)
    application_id = Column(Integer, ForeignKey("applications.id"))
    document_id = Column(Integer, ForeignKey("documents.id"))
    requested_by = Column(Integer, ForeignKey("users.id"))
    proposed_status = Column(String(40))
    justification = Column(Text)
    status = Column(String(20), default="pending")  # pending|approved|rejected
    approved_by = Column(Integer, ForeignKey("users.id"))
    approver_note = Column(Text)
    created_at = Column(DateTime, default=now)
    decided_at = Column(DateTime)


class Notification(Base):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    role = Column(String(20), nullable=True)
    college_id = Column(Integer, nullable=True)
    message = Column(Text)
    link = Column(String(200))
    read = Column(Boolean, default=False)
    kind = Column(String(40), nullable=True)
    severity = Column(String(12), default="info")
    created_at = Column(DateTime, default=now)


class NotificationOutbox(Base):
    """Durable retry queue for external channels (email/sms/webhook/slack/siem)."""
    __tablename__ = "notification_outbox"
    id = Column(Integer, primary_key=True)
    channel = Column(String(20), nullable=False)
    kind = Column(String(40))
    payload = Column(Text, nullable=False)
    status = Column(String(10), default="pending", index=True)  # pending | sent | dead
    attempts = Column(Integer, default=0)
    next_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=now)


@event.listens_for(AuditLog, "before_update")
def _no_audit_update(*_):
    raise RuntimeError("audit_log is append-only")


@event.listens_for(AuditLog, "before_delete")
def _no_audit_delete(*_):
    raise RuntimeError("audit_log is append-only")


@event.listens_for(DocumentVersion, "before_update")
def _no_version_update(*_):
    raise RuntimeError("document_versions are immutable (write-once)")


class Blob(Base):
    """Insert-only object store (STORAGE_BACKEND=db): originals and derived artefacts shared by every instance."""
    __tablename__ = "blobs"
    key = Column(String(200), primary_key=True)
    sha256 = Column(String(64), nullable=False)
    size = Column(Integer, nullable=False)
    data = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime, default=lambda: now())


class UserProfile(Base):
    """Details collected at first Google sign-in. Officer/admin access is never self-assigned: status=pending
    until an admin approves; college representatives are approved automatically for a new institution."""
    __tablename__ = "user_profiles"
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    google_sub = Column(String(64), unique=True)
    full_name = Column(String(120))
    requested_role = Column(String(20))          # college | officer
    institution_name = Column(String(200))
    aicte_id = Column(String(60))                # AICTE permanent institution ID or application ID
    state = Column(String(80))
    designation = Column(String(120))
    phone = Column(String(20))
    official_email = Column(String(200))
    consent_at = Column(DateTime)
    status = Column(String(12), default="new")   # new (form not filled) | pending | approved | rejected
    decided_by = Column(String(200))
    decided_at = Column(DateTime)
    decision_note = Column(Text)
    created_at = Column(DateTime, default=lambda: now())
    user = relationship("User", backref=backref("profile", uselist=False))
    __table_args__ = (CheckConstraint("status in ('new','pending','approved','rejected')", name="ck_profile_status"),)


PG_DDL = [
    "CREATE INDEX IF NOT EXISTS ix_photo_embedding_hnsw ON photo_index USING hnsw (embedding vector_cosine_ops)",
    "CREATE INDEX IF NOT EXISTS ix_doc_text_embedding_hnsw ON documents USING hnsw (text_embedding vector_cosine_ops)",
    """CREATE OR REPLACE FUNCTION sealcheck_append_only() RETURNS trigger AS $$
       BEGIN RAISE EXCEPTION '% is append-only', TG_TABLE_NAME; END; $$ LANGUAGE plpgsql""",
    "DROP TRIGGER IF EXISTS trg_audit_append_only ON audit_log",
    "CREATE TRIGGER trg_audit_append_only BEFORE UPDATE OR DELETE ON audit_log FOR EACH ROW EXECUTE FUNCTION sealcheck_append_only()",
    "DROP TRIGGER IF EXISTS trg_docver_immutable ON document_versions",
    "CREATE TRIGGER trg_docver_immutable BEFORE UPDATE ON document_versions FOR EACH ROW EXECUTE FUNCTION sealcheck_append_only()",
    "DROP TRIGGER IF EXISTS trg_blobs_insert_only ON blobs",
    "CREATE TRIGGER trg_blobs_insert_only BEFORE UPDATE OR DELETE ON blobs FOR EACH ROW EXECUTE FUNCTION sealcheck_append_only()",
]


def init_db():
    """Idempotent schema setup. On PostgreSQL it runs under an advisory lock so concurrent cold starts
    (several serverless instances) cannot race; `alembic upgrade head` produces the same DDL."""
    if not IS_PG:
        Base.metadata.create_all(engine)
        return
    with engine.begin() as c:
        c.execute(text("SELECT pg_advisory_xact_lock(726354)"))
        c.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        Base.metadata.create_all(c)
        for stmt in PG_DDL:
            c.execute(text(stmt))
        c.execute(text("ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_role"))
        c.execute(text("ALTER TABLE users ADD CONSTRAINT ck_users_role CHECK (role in "
                       "('college','officer','senior_officer','admin','pending'))"))


def reset_db():
    """Drop everything (dev/test seeding only; refused in production by seed script)."""
    if IS_PG:
        with engine.begin() as c:
            c.execute(text("DROP SCHEMA public CASCADE")); c.execute(text("CREATE SCHEMA public"))
    else:
        Base.metadata.drop_all(engine)


def similar_photos(s, emb, exclude_college_id, limit=10):
    """Nearest photos by cosine distance. pgvector index on Postgres; numpy scan on SQLite."""
    if emb is None:
        return []
    if IS_PG:
        dist = PhotoIndex.embedding.cosine_distance(emb)
        rows = (s.query(PhotoIndex, dist.label("d")).filter(PhotoIndex.college_id != exclude_college_id,
                PhotoIndex.embedding.isnot(None)).order_by(dist).limit(limit).all())
        return [(p, 1 - float(d)) for p, d in rows]
    import numpy as np
    q = np.asarray(emb, dtype=float); q /= (np.linalg.norm(q) or 1)
    out = []
    for p in s.query(PhotoIndex).filter(PhotoIndex.college_id != exclude_college_id, PhotoIndex.embedding.isnot(None)).all():
        v = np.asarray(p.embedding, dtype=float); v /= (np.linalg.norm(v) or 1)
        out.append((p, float(q @ v)))
    return sorted(out, key=lambda t: -t[1])[:limit]
