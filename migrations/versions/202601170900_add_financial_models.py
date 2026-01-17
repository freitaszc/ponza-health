"""Add financial models - Cashbox, CashboxTransaction, PatientPayment

Revision ID: 202601170900
Revises: 202601160900
Create Date: 2026-01-17 09:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '202601170900'
down_revision = '202601160900'
branch_labels = None
depends_on = None


def upgrade():
    # Create cashboxes table
    op.create_table(
        'cashboxes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('type', sa.String(length=50), nullable=False, server_default='manual'),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='open'),
        sa.Column('initial_balance', sa.Float(), nullable=False, server_default='0'),
        sa.Column('current_balance', sa.Float(), nullable=False, server_default='0'),
        sa.Column('opened_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('closed_at', sa.DateTime(), nullable=True),
        sa.Column('responsible', sa.String(length=120), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_cashboxes_status', 'cashboxes', ['status'])
    op.create_index('ix_cashboxes_type', 'cashboxes', ['type'])
    op.create_index('ix_cashboxes_opened_at', 'cashboxes', ['opened_at'])
    op.create_index('ix_cashboxes_user_id', 'cashboxes', ['user_id'])

    # Create patient_payments table
    op.create_table(
        'patient_payments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('patient_id', sa.Integer(), nullable=False),
        sa.Column('event_id', sa.Integer(), nullable=True),
        sa.Column('amount', sa.Float(), nullable=False),
        sa.Column('amount_paid', sa.Float(), nullable=False, server_default='0'),
        sa.Column('payment_method', sa.String(length=50), nullable=True),
        sa.Column('payment_type', sa.String(length=50), nullable=False, server_default='consultation'),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('due_date', sa.Date(), nullable=True),
        sa.Column('paid_at', sa.DateTime(), nullable=True),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('insurance_name', sa.String(length=120), nullable=True),
        sa.Column('insurance_authorization', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['event_id'], ['agenda_events.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_patient_payments_status', 'patient_payments', ['status'])
    op.create_index('ix_patient_payments_payment_type', 'patient_payments', ['payment_type'])
    op.create_index('ix_patient_payments_due_date', 'patient_payments', ['due_date'])
    op.create_index('ix_patient_payments_created_at', 'patient_payments', ['created_at'])
    op.create_index('ix_patient_payments_user_id', 'patient_payments', ['user_id'])
    op.create_index('ix_patient_payments_patient_id', 'patient_payments', ['patient_id'])

    # Create cashbox_transactions table
    op.create_table(
        'cashbox_transactions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('cashbox_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('patient_payment_id', sa.Integer(), nullable=True),
        sa.Column('type', sa.String(length=20), nullable=False),
        sa.Column('category', sa.String(length=50), nullable=True),
        sa.Column('amount', sa.Float(), nullable=False),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('payment_method', sa.String(length=50), nullable=True),
        sa.Column('reference', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['cashbox_id'], ['cashboxes.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['patient_payment_id'], ['patient_payments.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_cashbox_transactions_type', 'cashbox_transactions', ['type'])
    op.create_index('ix_cashbox_transactions_category', 'cashbox_transactions', ['category'])
    op.create_index('ix_cashbox_transactions_created_at', 'cashbox_transactions', ['created_at'])
    op.create_index('ix_cashbox_transactions_cashbox_id', 'cashbox_transactions', ['cashbox_id'])
    op.create_index('ix_cashbox_transactions_user_id', 'cashbox_transactions', ['user_id'])


def downgrade():
    op.drop_table('cashbox_transactions')
    op.drop_table('patient_payments')
    op.drop_table('cashboxes')
