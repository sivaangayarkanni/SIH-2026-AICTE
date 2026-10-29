"""workflow tables (routes, stages, EVC, undertakings, validity, alerts, drafts, scheduler runs),
username/password credentials, 'evc_member' role

Revision ID: 0004
Revises: 0003
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

TABLES = ["wf_config_versions", "wf_user_regions", "wf_app_workflow", "wf_stage_events", "wf_evc_visits", "wf_undertakings",
          "wf_compliance_submissions", "wf_document_validity", "wf_alerts", "wf_wizard_drafts", "wf_scheduler_runs", "user_credentials"]


def upgrade():
    from app.db import Base
    from app import workflow, accounts  # noqa: F401
    bind = op.get_bind()
    Base.metadata.create_all(bind, tables=[Base.metadata.tables[t] for t in TABLES])
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_role")
        op.execute("ALTER TABLE users ADD CONSTRAINT ck_users_role CHECK (role in "
                   "('college','officer','senior_officer','evc_member','admin','pending'))")


def downgrade():
    for t in reversed(TABLES):
        op.drop_table(t)
