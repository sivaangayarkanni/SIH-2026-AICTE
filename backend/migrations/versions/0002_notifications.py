"""notification kind/severity + outbox

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("notifications") as b:
        b.add_column(sa.Column("kind", sa.String(40), nullable=True))
        b.add_column(sa.Column("severity", sa.String(12), nullable=True))
    op.create_table("notification_outbox",
                    sa.Column("id", sa.Integer, primary_key=True),
                    sa.Column("channel", sa.String(20), nullable=False),
                    sa.Column("kind", sa.String(40)),
                    sa.Column("payload", sa.Text, nullable=False),
                    sa.Column("status", sa.String(10)),
                    sa.Column("attempts", sa.Integer),
                    sa.Column("next_at", sa.DateTime),
                    sa.Column("last_error", sa.Text),
                    sa.Column("sent_at", sa.DateTime),
                    sa.Column("created_at", sa.DateTime))
    op.create_index("ix_notification_outbox_status", "notification_outbox", ["status"])


def downgrade():
    op.drop_index("ix_notification_outbox_status", "notification_outbox")
    op.drop_table("notification_outbox")
    with op.batch_alter_table("notifications") as b:
        b.drop_column("severity")
        b.drop_column("kind")
