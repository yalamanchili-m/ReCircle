"""External data ingestion: source registry, runs, raw files, records, WARM factors

Revision ID: b9e2d7c4f1a8
Revises: a8f3b1c5d9e2
Create Date: 2026-11-01 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'b9e2d7c4f1a8'
down_revision: Union[str, None] = 'a8f3b1c5d9e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'external_data_sources',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('key', sa.String(length=60), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('family', sa.String(length=40), nullable=False),
        sa.Column('jurisdiction', sa.String(length=10), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('homepage_url', sa.Text(), nullable=False),
        sa.Column('source_url', sa.Text(), nullable=True),
        sa.Column('terms_note', sa.Text(), nullable=False),
        sa.Column('access_note', sa.Text(), nullable=True),
        sa.Column('expected_format', sa.String(length=40), nullable=False),
        sa.Column('adapter', sa.String(length=40), nullable=True),
        sa.Column(
            'adapter_status', sa.String(length=30), server_default='planned',
            nullable=False,
        ),
        sa.Column('declared_version', sa.String(length=255), nullable=True),
        sa.Column('update_cadence', sa.String(length=60), nullable=False),
        sa.Column('enabled', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('latest_file_hash', sa.String(length=64), nullable=True),
        sa.Column(
            'latest_run_at', sa.DateTime(timezone=True), nullable=True,
        ),
        sa.Column(
            'created_at', sa.DateTime(timezone=True),
            server_default=sa.text('now()'), nullable=False,
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True),
            server_default=sa.text('now()'), nullable=False,
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key', name='uq_external_data_sources_key'),
    )

    op.create_table(
        'ingestion_runs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('source_id', sa.Uuid(), nullable=True),
        sa.Column('source_key', sa.String(length=60), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('mode', sa.String(length=20), server_default='manual', nullable=False),
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
        sa.ForeignKeyConstraint(
            ['source_id'], ['external_data_sources.id'], ondelete='SET NULL',
        ),
        sa.ForeignKeyConstraint(['triggered_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(
            "status IN ('success','failed','skipped')",
            name='ck_ing_runs_status',
        ),
        sa.CheckConstraint("mode IN ('manual','scheduled')", name='ck_ing_runs_mode'),
    )
    op.create_index(
        'idx_ing_runs_source_started', 'ingestion_runs',
        ['source_id', 'started_at'], unique=False,
    )
    op.create_index(
        'idx_ing_runs_status_started', 'ingestion_runs',
        ['status', 'started_at'], unique=False,
    )

    op.create_table(
        'ingestion_raw_files',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('source_id', sa.Uuid(), nullable=False),
        sa.Column('file_hash', sa.String(length=64), nullable=False),
        sa.Column('original_name', sa.String(length=260), nullable=False),
        sa.Column('stored_path', sa.Text(), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('declared_version', sa.String(length=255), nullable=True),
        sa.Column('import_count', sa.Integer(), server_default='1', nullable=False),
        sa.Column(
            'first_imported_at', sa.DateTime(timezone=True),
            server_default=sa.text('now()'), nullable=False,
        ),
        sa.Column(
            'last_imported_at', sa.DateTime(timezone=True),
            server_default=sa.text('now()'), nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ['source_id'], ['external_data_sources.id'], ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('source_id', 'file_hash', name='uq_ing_raw_source_hash'),
    )
    op.create_index(
        'idx_ing_raw_source_first', 'ingestion_raw_files',
        ['source_id', 'first_imported_at'], unique=False,
    )

    op.create_table(
        'ingestion_records',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('source_id', sa.Uuid(), nullable=False),
        sa.Column('natural_key', sa.String(length=200), nullable=False),
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
        sa.ForeignKeyConstraint(
            ['source_id'], ['external_data_sources.id'], ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['run_id'], ['ingestion_runs.id'], ondelete='SET NULL',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'source_id', 'natural_key', 'content_hash',
            name='uq_ing_records_key_hash',
        ),
        sa.CheckConstraint(
            "status IN ('active','superseded','quarantined')",
            name='ck_ing_records_status',
        ),
    )
    op.create_index(
        'idx_ing_records_source_status', 'ingestion_records',
        ['source_id', 'status'], unique=False,
    )

    op.create_table(
        'ingestion_warm_factors',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('run_id', sa.Uuid(), nullable=True),
        sa.Column('catalog_version', sa.String(length=80), nullable=False),
        sa.Column('factor_source', sa.String(length=180), nullable=False),
        sa.Column('category', sa.String(length=80), nullable=False),
        sa.Column('pathway', sa.String(length=40), nullable=False),
        sa.Column('value', sa.Numeric(14, 4), nullable=False),
        sa.Column('uncertainty_ratio', sa.Numeric(6, 4), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('provenance', postgresql.JSONB(), server_default='{}', nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column(
            'created_at', sa.DateTime(timezone=True),
            server_default=sa.text('now()'), nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ['run_id'], ['ingestion_runs.id'], ondelete='SET NULL',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(
            'uncertainty_ratio >= 0 AND uncertainty_ratio <= 1',
            name='ck_ing_warm_uncertainty',
        ),
    )
    op.create_index(
        'idx_ing_warm_version_cat', 'ingestion_warm_factors',
        ['catalog_version', 'category', 'pathway'], unique=False,
    )
    op.create_index(
        'uq_ing_warm_active', 'ingestion_warm_factors',
        ['category', 'pathway'], unique=True,
        postgresql_where=sa.text('is_active'),
    )


def downgrade() -> None:
    op.drop_index('uq_ing_warm_active', table_name='ingestion_warm_factors')
    op.drop_index('idx_ing_warm_version_cat', table_name='ingestion_warm_factors')
    op.drop_table('ingestion_warm_factors')
    op.drop_index('idx_ing_records_source_status', table_name='ingestion_records')
    op.drop_table('ingestion_records')
    op.drop_index('idx_ing_raw_source_first', table_name='ingestion_raw_files')
    op.drop_table('ingestion_raw_files')
    op.drop_index('idx_ing_runs_status_started', table_name='ingestion_runs')
    op.drop_index('idx_ing_runs_source_started', table_name='ingestion_runs')
    op.drop_table('ingestion_runs')
    op.drop_table('external_data_sources')

