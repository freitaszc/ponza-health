"""add clinic_address to user

Revision ID: 202411041200
Revises: 
Create Date: 2025-11-04 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "202411041200"
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Idempotente: só adiciona se não existir (evita DuplicateColumn em bases já ajustadas manualmente)
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("users")}
    if "clinic_address" not in cols:
        op.add_column("users", sa.Column("clinic_address", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "clinic_address")
