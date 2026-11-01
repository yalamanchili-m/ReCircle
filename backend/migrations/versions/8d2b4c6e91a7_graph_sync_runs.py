"""graph sync runs

Revision ID: 8d2b4c6e91a7
Revises: 3f7a1c9e5b20
Create Date: 2026-10-27 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '8d2b4c6e91a7'
down_revision: Union[str, None] = '3f7a1c9e5b20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('graph_sync_runs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('stats', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('projection_version', sa.String(length=40), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_graph_sync_runs_status', 'graph_sync_runs', ['status', 'started_at'], unique=False)


def downgrade() -> None:
    op.drop_index('idx_graph_sync_runs_status', table_name='graph_sync_runs')
    op.drop_table('graph_sync_runs')
