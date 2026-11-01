"""Regulation-news aggregator: sources, items, refresh runs

Revision ID: d5a9c2f3b7e1
Revises: 1c5d8e7f9a2b
Create Date: 2026-10-28 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'd5a9c2f3b7e1'
down_revision: Union[str, None] = '1c5d8e7f9a2b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'regulation_news_sources',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('key', sa.String(length=60), nullable=False),
        sa.Column('name', sa.String(length=160), nullable=False),
        sa.Column('kind', sa.String(length=40), nullable=False),
        sa.Column('jurisdiction', sa.String(length=10), nullable=False),
        sa.Column('homepage_url', sa.Text(), nullable=False),
        sa.Column('feed_url', sa.Text(), nullable=True),
        sa.Column(
            'topics', postgresql.JSONB(astext_type=sa.Text()),
            server_default='[]', nullable=False,
        ),
        sa.Column('terms_note', sa.Text(), nullable=False),
        sa.Column(
            'enabled', sa.Boolean(), server_default='false', nullable=False
        ),
        sa.Column('last_fetched_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_item_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True),
            server_default=sa.text('now()'), nullable=False,
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True),
            server_default=sa.text('now()'), nullable=False,
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key', name='uq_regnews_sources_key'),
    )
    op.create_table(
        'regulation_news_items',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('source_id', sa.Uuid(), nullable=False),
        sa.Column('item_type', sa.String(length=20), nullable=False),
        sa.Column('title', sa.String(length=400), nullable=False),
        sa.Column('url', sa.Text(), nullable=False),
        sa.Column('url_hash', sa.String(length=64), nullable=False),
        sa.Column('content_hash', sa.String(length=64), nullable=False),
        sa.Column('issuer', sa.String(length=200), nullable=True),
        sa.Column('jurisdiction', sa.String(length=10), nullable=False),
        sa.Column(
            'topics', postgresql.JSONB(astext_type=sa.Text()),
            server_default='[]', nullable=False,
        ),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column(
            'summary_kind', sa.String(length=30), server_default='source_excerpt',
            nullable=False,
        ),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'fetched_at', sa.DateTime(timezone=True),
            server_default=sa.text('now()'), nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ['source_id'], ['regulation_news_sources.id'], ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(
            "item_type IN ('regulation','news')", name='ck_regnews_item_type'
        ),
        sa.UniqueConstraint(
            'source_id', 'url_hash', name='uq_regnews_source_urlhash'
        ),
    )
    op.create_index(
        'idx_regnews_type_published',
        'regulation_news_items',
        ['item_type', 'published_at'],
        unique=False,
    )
    op.create_index(
        'idx_regnews_jurisdiction_published',
        'regulation_news_items',
        ['jurisdiction', 'published_at'],
        unique=False,
    )
    op.create_index(
        'idx_regnews_source_fetched',
        'regulation_news_items',
        ['source_id', 'fetched_at'],
        unique=False,
    )
    op.create_table(
        'regulation_refresh_runs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column(
            'mode', sa.String(length=20), server_default='manual', nullable=False
        ),
        sa.Column(
            'params', postgresql.JSONB(astext_type=sa.Text()),
            server_default='{}', nullable=False,
        ),
        sa.Column(
            'stats', postgresql.JSONB(astext_type=sa.Text()),
            server_default='{}', nullable=False,
        ),
        sa.Column(
            'runtime_ms', sa.Integer(), nullable=False, server_default='0'
        ),
        sa.Column('triggered_by', sa.Uuid(), nullable=True),
        sa.Column(
            'started_at', sa.DateTime(timezone=True),
            server_default=sa.text('now()'), nullable=False,
        ),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ['triggered_by'], ['users.id'], ondelete='SET NULL'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(
            "status IN ('success','failed')", name='ck_regnews_refresh_status'
        ),
        sa.CheckConstraint(
            "mode IN ('manual','scheduled')", name='ck_regnews_refresh_mode'
        ),
    )
    op.create_index(
        'idx_regnews_refresh_runs',
        'regulation_refresh_runs',
        ['status', 'started_at'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        'idx_regnews_refresh_runs', table_name='regulation_refresh_runs'
    )
    op.drop_table('regulation_refresh_runs')
    op.drop_index(
        'idx_regnews_source_fetched', table_name='regulation_news_items'
    )
    op.drop_index(
        'idx_regnews_jurisdiction_published', table_name='regulation_news_items'
    )
    op.drop_index(
        'idx_regnews_type_published', table_name='regulation_news_items'
    )
    op.drop_table('regulation_news_items')
    op.drop_table('regulation_news_sources')
