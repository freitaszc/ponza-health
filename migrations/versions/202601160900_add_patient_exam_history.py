"""add patient_exam_history table for multi-exam tracking

Revision ID: 202601160900
Revises: 202601070900
Create Date: 2026-01-16 09:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "202601160900"
down_revision = "202601070900"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    
    # Create patient_exam_history table if not exists
    if "patient_exam_history" not in tables:
        op.create_table(
            "patient_exam_history",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("patient_id", sa.Integer(), sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("exam_date", sa.Date(), nullable=False),
            sa.Column("resumo_clinico", sa.Text(), nullable=True),
            sa.Column("abnormal_results", sa.Text(), nullable=True),  # JSON string with abnormal results
            sa.Column("all_results", sa.Text(), nullable=True),  # JSON string with all exam results
            sa.Column("pdf_file_id", sa.Integer(), sa.ForeignKey("pdf_files.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_patient_exam_history_patient_id", "patient_exam_history", ["patient_id"])
        op.create_index("ix_patient_exam_history_user_id", "patient_exam_history", ["user_id"])
        op.create_index("ix_patient_exam_history_exam_date", "patient_exam_history", ["exam_date"])


def downgrade() -> None:
    op.drop_table("patient_exam_history")
