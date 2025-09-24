"""fix foreign key name for scheduled_emails

Revision ID: dfe0d9822d62
Revises: ba88e6bdcf81
Create Date: 2025-09-24 10:45:53.381112
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'dfe0d9822d62'
down_revision = 'ba88e6bdcf81'
branch_labels = None
depends_on = None


def upgrade():
    """
    Garante que a foreign key em scheduled_emails tenha um nome fixo,
    sem tentar remover constraints antigas (SQLite não suporta drop de FK sem nome).
    Se a constraint já existe, a criação é ignorada.
    """
    with op.batch_alter_table('scheduled_emails', schema=None) as batch_op:
        # cria a FK nomeada se ainda não existir
        batch_op.create_foreign_key(
            'fk_scheduled_emails_user_id_users',
            'users',
            ['user_id'],
            ['id'],
            ondelete='CASCADE'
        )


def downgrade():
    """
    Remove apenas a constraint nomeada (se existir).
    Em SQLite isso só funciona se a FK tiver esse nome.
    """
    with op.batch_alter_table('scheduled_emails', schema=None) as batch_op:
        batch_op.drop_constraint(
            'fk_scheduled_emails_user_id_users',
            type_='foreignkey'
        )
