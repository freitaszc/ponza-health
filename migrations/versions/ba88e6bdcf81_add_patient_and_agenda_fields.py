from alembic import op
import sqlalchemy as sa


def upgrade():
    bind = op.get_bind()
    dialect = bind.dialect.name  # 'sqlite', 'postgresql', etc.

    # -----------------------
    # PATIENTS: adicionar colunas novas (todas como NULL para compatibilidade)
    # -----------------------
    with op.batch_alter_table('patients', schema=None) as batch_op:
        # Novos campos de cadastro
        batch_op.add_column(sa.Column('birthdate', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('sex', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('email', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('notes', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('phone_primary', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('phone_secondary', sa.String(length=20), nullable=True))

        # Endereço
        batch_op.add_column(sa.Column('address_cep', sa.String(length=12), nullable=True))
        batch_op.add_column(sa.Column('address_street', sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column('address_number', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('address_complement', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('address_district', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('address_city', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('address_state', sa.String(length=2), nullable=True))

        # Dono do cadastro (User); deixamos NULL aqui, criamos FK fora do batch se não for SQLite
        batch_op.add_column(sa.Column('owner_user_id', sa.Integer(), nullable=True))

    # Índices (criados fora do batch)
    op.create_index('ix_patients_email', 'patients', ['email'], unique=False)
    op.create_index('ix_patients_cpf', 'patients', ['cpf'], unique=False)
    op.create_index('ix_patients_phone_primary', 'patients', ['phone_primary'], unique=False)
    op.create_index('ix_patients_status', 'patients', ['status'], unique=False)
    op.create_index('ix_patients_owner_user_id', 'patients', ['owner_user_id'], unique=False)
    op.create_index('ix_patients_created_at', 'patients', ['created_at'], unique=False)

    # FK só em bancos que suportam ADD CONSTRAINT (SQLite não suporta). Dê um NOME à constraint.
    if dialect != 'sqlite':
        op.create_foreign_key(
            'fk_patients_owner_user_id_users',
            'patients', 'users',
            local_cols=['owner_user_id'], remote_cols=['id'],
        )

    # -----------------------
    # AGENDA_EVENTS: campos extras (se ainda não existirem)
    # -----------------------
    with op.batch_alter_table('agenda_events', schema=None) as batch_op:
        try:
            batch_op.add_column(sa.Column('notes', sa.Text(), nullable=True))
        except Exception:
            pass
        try:
            batch_op.add_column(sa.Column('type', sa.String(length=20), nullable=True))
        except Exception:
            pass
        try:
            batch_op.add_column(sa.Column('billing', sa.String(length=20), nullable=True))
        except Exception:
            pass
        try:
            batch_op.add_column(sa.Column('insurer', sa.String(length=120), nullable=True))
        except Exception:
            pass

    # Índices úteis na agenda
    op.create_index('ix_agenda_events_start', 'agenda_events', ['start'], unique=False)
    op.create_index('ix_agenda_events_end', 'agenda_events', ['end'], unique=False)
    op.create_index('ix_agenda_events_type', 'agenda_events', ['type'], unique=False)


def downgrade():
    bind = op.get_bind()
    dialect = bind.dialect.name

    # Remover índices da agenda
    op.drop_index('ix_agenda_events_type', table_name='agenda_events')
    op.drop_index('ix_agenda_events_end', table_name='agenda_events')
    op.drop_index('ix_agenda_events_start', table_name='agenda_events')

    # Remover colunas extras da agenda (tolerante se já não existirem)
    with op.batch_alter_table('agenda_events', schema=None) as batch_op:
        for col in ('insurer', 'billing', 'type', 'notes'):
            try:
                batch_op.drop_column(col)
            except Exception:
                pass

    # Remover FK se foi criada
    if dialect != 'sqlite':
        try:
            op.drop_constraint('fk_patients_owner_user_id_users', 'patients', type_='foreignkey')
        except Exception:
            pass

    # Remover índices de patients
    for idx in (
        'ix_patients_created_at',
        'ix_patients_owner_user_id',
        'ix_patients_status',
        'ix_patients_phone_primary',
        'ix_patients_cpf',
        'ix_patients_email',
    ):
        try:
            op.drop_index(idx, table_name='patients')
        except Exception:
            pass

    # Remover colunas de patients (tolerante)
    with op.batch_alter_table('patients', schema=None) as batch_op:
        for col in (
            'owner_user_id',
            'address_state','address_city','address_district','address_complement',
            'address_number','address_street','address_cep',
            'phone_secondary','phone_primary','notes','email','sex','birthdate'
        ):
            try:
                batch_op.drop_column(col)
            except Exception:
                pass
