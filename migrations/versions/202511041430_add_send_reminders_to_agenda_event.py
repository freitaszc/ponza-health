"""add send_reminders to agenda_event

Revision ID: 202511041430
Revises: 202411041200
Create Date: 2025-11-04 14:30:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "202511041430"
down_revision = "202411041200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agenda_events",
        sa.Column(
            "send_reminders",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.alter_column("agenda_events", "send_reminders", server_default=None)


def downgrade() -> None:
    op.drop_column("agenda_events", "send_reminders")
