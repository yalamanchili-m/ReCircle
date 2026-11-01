"""Assistant RAG: knowledge chunks + run records

Revision ID: a8f3b1c5d9e2
Revises: d5a9c2f3b7e1
Create Date: 2026-10-29 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'a8f3b1c5d9e2'
down_revision: Union[str, None] = 'd5a9c2f3b7e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'assistant_knowledge_chunks',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('chunk_key', sa.String(length=120), nullable=False),
        sa.Column('source_type', sa.String(length=40), nullable=False),
        sa.Column('source_ref_id', sa.String(length=80), nullable=True),
        sa.Column('title', sa.String(length=300), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('content_hash', sa.String(length=64), nullable=False),
        sa.Column(
            'access_scope', sa.String(length=30), server_default='platform',
            nullable=False,
        ),
        sa.Column(
            'idx_ordinal', sa.Integer(), server_default='0', nullable=False
        ),
        sa.Column(
            'is_trusted', sa.Boolean(), server_default='false', nullable=False
        ),
        sa.Column(
            'is_active', sa.Boolean(), server_default='true', nullable=False
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
        sa.UniqueConstraint('chunk_key', name='uq_assistant_chunks_key'),
        sa.CheckConstraint(
            "source_type IN ('method_document','platform_note','regulation_item')",
            name='ck_assistant_chunks_source_type',
        ),
        sa.CheckConstraint(
            "access_scope IN ('platform')",
            name='ck_assistant_chunks_access_scope',
        ),
    )
    op.create_index(
        'idx_assistant_chunks_active_source',
        'assistant_knowledge_chunks',
        ['is_active', 'source_type'],
        unique=False,
    )
    op.create_table(
        'assistant_runs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=True),
        sa.Column('organization_id', sa.Uuid(), nullable=True),
        sa.Column('question', sa.Text(), nullable=False),
        sa.Column('mode', sa.String(length=20), nullable=False),
        sa.Column('answer', sa.Text(), nullable=True),
        sa.Column(
            'citations', postgresql.JSONB(astext_type=sa.Text()),
            server_default='[]', nullable=False,
        ),
        sa.Column(
            'retrieval_stats', postgresql.JSONB(astext_type=sa.Text()),
            server_default='{}', nullable=False,
        ),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('retrieval_version', sa.String(length=40), nullable=False),
        sa.Column('prompt_version', sa.String(length=40), nullable=False),
        sa.Column('model_name', sa.String(length=120), nullable=True),
        sa.Column(
            'runtime_ms', sa.Integer(), nullable=False, server_default='0'
        ),
        sa.Column(
            'created_at', sa.DateTime(timezone=True),
            server_default=sa.text('now()'), nullable=False,
        ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(
            ['organization_id'], ['organizations.id'], ondelete='SET NULL'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(
            "mode IN ('generated','retrieve_only','abstained','refused')",
            name='ck_assistant_runs_mode',
        ),
    )
    op.create_index(
        'idx_assistant_runs_user',
        'assistant_runs',
        ['user_id', 'created_at'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('idx_assistant_runs_user', table_name='assistant_runs')
    op.drop_table('assistant_runs')
    op.drop_index(
        'idx_assistant_chunks_active_source', table_name='assistant_knowledge_chunks'
    )
    op.drop_table('assistant_knowledge_chunks')
