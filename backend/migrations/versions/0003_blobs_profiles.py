"""insert-only blob store (STORAGE_BACKEND=db), Google sign-up profiles, 'pending' role

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("blobs",
                    sa.Column("key", sa.String(200), primary_key=True),
                    sa.Column("sha256", sa.String(64), nullable=False),
                    sa.Column("size", sa.Integer, nullable=False),
                    sa.Column("data", sa.LargeBinary, nullable=False),
                    sa.Column("created_at", sa.DateTime))
    op.create_table("user_profiles",
                    sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), primary_key=True),
                    sa.Column("google_sub", sa.String(64), unique=True),
                    sa.Column("full_name", sa.String(120)), sa.Column("requested_role", sa.String(20)),
                    sa.Column("institution_name", sa.String(200)), sa.Column("aicte_id", sa.String(60)),
                    sa.Column("state", sa.String(80)), sa.Column("designation", sa.String(120)),
                    sa.Column("phone", sa.String(20)), sa.Column("official_email", sa.String(200)),
                    sa.Column("consent_at", sa.DateTime), sa.Column("status", sa.String(12)),
                    sa.Column("decided_by", sa.String(200)), sa.Column("decided_at", sa.DateTime),
                    sa.Column("decision_note", sa.Text), sa.Column("created_at", sa.DateTime),
                    sa.CheckConstraint("status in ('new','pending','approved','rejected')", name="ck_profile_status"))
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_blobs_insert_only ON blobs")
        op.execute("CREATE TRIGGER trg_blobs_insert_only BEFORE UPDATE OR DELETE ON blobs FOR EACH ROW "
                   "EXECUTE FUNCTION sealcheck_append_only()")
        op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_role")
        op.execute("ALTER TABLE users ADD CONSTRAINT ck_users_role CHECK (role in "
                   "('college','officer','senior_officer','admin','pending'))")


def downgrade():
    op.drop_table("user_profiles")
    op.drop_table("blobs")
