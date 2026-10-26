"""symbiosis runs

Revision ID: b6e8f2a4c7d9
Revises: 8d2b4c6e91a7
Create Date: 2026-10-27 16:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'b6e8f2a4c7d9'
down_revision: Union[str, None] = '8d2b4c6e91a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('symbiosis_runs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('params', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('stats', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('graph_snapshot_id', sa.String(length=80), nullable=True),
    sa.Column('discovery_version', sa.String(length=40), nullable=False),
    sa.Column('taxonomy_version', sa.String(length=40), nullable=False),
    sa.Column('runtime_ms', sa.Integer(), server_default='0', nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_symbiosis_runs_status', 'symbiosis_runs', ['status', 'started_at'], unique=False)


def downgrade() -> None:
    op.drop_index('idx_symbiosis_runs_status', table_name='symbiosis_runs')
    op.drop_table('symbiosis_runs')
