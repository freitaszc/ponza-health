"""add patient extra fields

Revision ID: 202511051200
Revises: 202511041430
Create Date: 2025-11-05 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "202511051200"
down_revision = "202511041430"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("patients", sa.Column("rg", sa.String(length=20), nullable=True))
    op.add_column("patients", sa.Column("marital_status", sa.String(length=40), nullable=True))
    op.add_column("patients", sa.Column("father_name", sa.String(length=120), nullable=True))
    op.add_column("patients", sa.Column("mother_name", sa.String(length=120), nullable=True))
    op.add_column("patients", sa.Column("education_level", sa.String(length=80), nullable=True))
    op.add_column("patients", sa.Column("profession", sa.String(length=120), nullable=True))
    op.add_column("patients", sa.Column("monthly_income", sa.String(length=40), nullable=True))
    op.add_column("patients", sa.Column("special_needs", sa.String(length=120), nullable=True))
    op.add_column("patients", sa.Column("emergency_contact_name", sa.String(length=120), nullable=True))
    op.add_column("patients", sa.Column("emergency_contact_phone", sa.String(length=20), nullable=True))
    op.add_column(
        "patients",
        sa.Column(
            "has_health_plan",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.alter_column("patients", "has_health_plan", server_default=None)


def downgrade() -> None:
    op.drop_column("patients", "has_health_plan")
    op.drop_column("patients", "emergency_contact_phone")
    op.drop_column("patients", "emergency_contact_name")
    op.drop_column("patients", "special_needs")
    op.drop_column("patients", "monthly_income")
    op.drop_column("patients", "profession")
    op.drop_column("patients", "education_level")
    op.drop_column("patients", "mother_name")
    op.drop_column("patients", "father_name")
    op.drop_column("patients", "marital_status")
    op.drop_column("patients", "rg")
