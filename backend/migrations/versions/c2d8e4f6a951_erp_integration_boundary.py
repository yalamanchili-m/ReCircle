"""ERP integration boundary: staging runs and records

Revision ID: c2d8e4f6a951
Revises: b9e2d7c4f1a8
Create Date: 2026-11-03 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'c2d8e4f6a951'
down_revision: Union[str, None] = 'b9e2d7c4f1a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'erp_runs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('adapter_key', sa.String(length=60), nullable=False),
        sa.Column('entity_type', sa.String(length=60), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('mode', sa.String(length=20), server_default='preview', nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('params', postgresql.JSONB(), server_default='{}', nullable=False),
        sa.Column('stats', postgresql.JSONB(), server_default='{}', nullable=False),
        sa.Column('file_hash', sa.String(length=64), nullable=True),
        sa.Column('runtime_ms', sa.Integer(), server_default='0', nullable=False),
        sa.Column('triggered_by', sa.Uuid(), nullable=True),
        sa.Column(
            'started_at', sa.DateTime(timezone=True),
            server_default=sa.text('now()'), nullable=False,
        ),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['triggered_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(
            "status IN ('previewed','success','failed','skipped')",
            name='ck_erp_runs_status',
        ),
        sa.CheckConstraint("mode IN ('preview','confirm')", name='ck_erp_runs_mode'),
    )
    op.create_index(
        'idx_erp_runs_adapter_started', 'erp_runs',
        ['adapter_key', 'entity_type', 'started_at'], unique=False,
    )
    op.create_index(
        'idx_erp_runs_status_started', 'erp_runs',
        ['status', 'started_at'], unique=False,
    )

    op.create_table(
        'erp_records',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('adapter_key', sa.String(length=60), nullable=False),
        sa.Column('entity_type', sa.String(length=60), nullable=False),
        sa.Column('external_key', sa.String(length=200), nullable=False),
        sa.Column('content_hash', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('row_data', postgresql.JSONB(), server_default='{}', nullable=False),
        sa.Column('provenance', postgresql.JSONB(), server_default='{}', nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('run_id', sa.Uuid(), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True),
            server_default=sa.text('now()'), nullable=False,
        ),
        sa.ForeignKeyConstraint(['run_id'], ['erp_runs.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'adapter_key', 'entity_type', 'external_key', 'content_hash',
            name='uq_erp_records_key_hash',
        ),
        sa.CheckConstraint(
            "status IN ('active','superseded','quarantined')",
            name='ck_erp_records_status',
        ),
    )
    op.create_index(
        'idx_erp_records_entity_status', 'erp_records',
        ['adapter_key', 'entity_type', 'status'], unique=False,
    )


def downgrade() -> None:
    op.drop_index('idx_erp_records_entity_status', table_name='erp_records')
    op.drop_table('erp_records')
    op.drop_index('idx_erp_runs_status_started', table_name='erp_runs')
    op.drop_index('idx_erp_runs_adapter_started', table_name='erp_runs')
    op.drop_table('erp_runs')
