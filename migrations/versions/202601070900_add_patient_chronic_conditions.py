"""add chronic_conditions to patients

Revision ID: 202601070900
Revises: 202511051200
Create Date: 2026-01-07 09:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "202601070900"
down_revision = "202511051200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotente: só cria se não existir (caso já tenha sido criada manualmente)
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("patients")}
    if "chronic_conditions" not in cols:
        op.add_column("patients", sa.Column("chronic_conditions", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("patients", "chronic_conditions")
