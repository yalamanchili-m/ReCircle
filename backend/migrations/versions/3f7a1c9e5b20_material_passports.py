"""material passports

Revision ID: 3f7a1c9e5b20
Revises: cea306e032a5
Create Date: 2026-10-27 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '3f7a1c9e5b20'
down_revision: Union[str, None] = 'cea306e032a5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('material_passports',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('listing_id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('status', sa.String(length=20), server_default='active', nullable=False),
    sa.Column('attributes', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('possible_applications', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    sa.Column('suitable_industries', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    sa.Column('candidate_pathways', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('review_status', sa.String(length=20), server_default='unreviewed', nullable=False),
    sa.Column('reviewed_by', sa.Uuid(), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('active', 'superseded')", name='ck_passports_status'),
    sa.CheckConstraint("review_status IN ('unreviewed', 'reviewed')", name='ck_passports_review_status'),
    sa.CheckConstraint('version >= 1', name='ck_passports_version_positive'),
    sa.ForeignKeyConstraint(['listing_id'], ['waste_listings.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
    sa.ForeignKeyConstraint(['reviewed_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('listing_id', 'version', name='uq_passports_listing_version')
    )
    op.create_index('idx_passports_listing_status', 'material_passports', ['listing_id', 'status'], unique=False)
    op.create_index('idx_passports_organization', 'material_passports', ['organization_id'], unique=False)


def downgrade() -> None:
    op.drop_index('idx_passports_organization', table_name='material_passports')
    op.drop_index('idx_passports_listing_status', table_name='material_passports')
    op.drop_table('material_passports')
