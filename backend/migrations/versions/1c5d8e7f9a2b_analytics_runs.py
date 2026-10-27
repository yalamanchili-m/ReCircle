"""Analytics runs: marketplace metrics + K-means run records

Revision ID: 1c5d8e7f9a2b
Revises: e2f9d3a1b4c8
Create Date: 2026-10-27 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '1c5d8e7f9a2b'
down_revision: Union[str, None] = 'e2f9d3a1b4c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'analytics_runs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('run_kind', sa.String(length=40), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column(
            'params',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default='{}',
            nullable=False,
        ),
        sa.Column(
            'feature_schema',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default='{}',
            nullable=False,
        ),
        sa.Column(
            'stats',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default='{}',
            nullable=False,
        ),
        sa.Column(
            'sampling_summary',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default='{}',
            nullable=False,
        ),
        sa.Column('result_version', sa.String(length=40), nullable=False),
        sa.Column('subjects', sa.String(length=120), nullable=False),
        sa.Column(
            'runtime_ms', sa.Integer(), nullable=False, server_default='0'
        ),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column(
            'started_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(
            "status IN ('success','failed')", name='ck_analytics_runs_status'
        ),
        sa.CheckConstraint(
            "run_kind IN ('marketplace_metrics','kmeans')",
            name='ck_analytics_runs_kind',
        ),
    )
    op.create_foreign_key(
        'fk_analytics_runs_created_by_users',
        'analytics_runs',
        'users',
        ['created_by'],
        ['id'],
        ondelete='SET NULL',
    )
    op.create_index(
        'idx_analytics_runs_kind',
        'analytics_runs',
        ['run_kind', 'status', 'started_at'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('idx_analytics_runs_kind', table_name='analytics_runs')
    op.drop_constraint(
        'fk_analytics_runs_created_by_users', 'analytics_runs', type_='foreignkey'
    )
    op.drop_table('analytics_runs')
