"""ESG foundations: recovery verification + impact estimates

Revision ID: e2f9d3a1b4c8
Revises: b6e8f2a4c7d9
Create Date: 2026-10-27 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'e2f9d3a1b4c8'
down_revision: Union[str, None] = 'b6e8f2a4c7d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'recovery_records',
        sa.Column(
            'verification_status',
            sa.String(length=20),
            server_default='unverified',
            nullable=False,
        ),
    )
    op.add_column(
        'recovery_records', sa.Column('verified_by', sa.Uuid(), nullable=True)
    )
    op.add_column(
        'recovery_records', sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True)
    )
    op.create_check_constraint(
        'ck_recovery_verification_status',
        'recovery_records',
        "verification_status IN ('unverified', 'verified')",
    )
    op.create_foreign_key(
        'fk_recovery_records_verified_by_users',
        'recovery_records',
        'users',
        ['verified_by'],
        ['id'],
        ondelete='SET NULL',
    )

    op.create_table(
        'impact_estimates',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column(
            'recovery_record_id',
            sa.Uuid(),
            nullable=False,
        ),
        sa.Column('recovery_route', sa.String(length=80), nullable=True),
        sa.Column('supported', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('unsupported_reason', sa.Text(), nullable=True),
        sa.Column('quantity', sa.Numeric(14, 3), nullable=True),
        sa.Column('unit', sa.String(length=20), nullable=True),
        sa.Column('quantity_tonnes', sa.Numeric(14, 6), nullable=True),
        sa.Column('avoided_co2e_kg', sa.Numeric(14, 3), nullable=True),
        sa.Column('landfill_diverted_kg', sa.Numeric(14, 3), nullable=True),
        sa.Column('method', sa.String(length=60), nullable=False),
        sa.Column('factor_catalog_version', sa.String(length=60), nullable=False),
        sa.Column('factor_source', sa.String(length=180), nullable=False),
        sa.Column('baseline_reference', sa.String(length=180), nullable=False),
        sa.Column(
            'assumptions',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default='{}',
            nullable=False,
        ),
        sa.Column('is_current', sa.Boolean(), server_default='true', nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ['recovery_record_id'],
            ['recovery_records.id'],
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'idx_impact_estimates_recovery',
        'impact_estimates',
        ['recovery_record_id'],
        unique=False,
    )
    op.create_index(
        'uq_impact_estimates_current',
        'impact_estimates',
        ['recovery_record_id'],
        unique=True,
        postgresql_where=sa.text('is_current'),
    )


def downgrade() -> None:
    op.drop_index('uq_impact_estimates_current', table_name='impact_estimates')
    op.drop_index('idx_impact_estimates_recovery', table_name='impact_estimates')
    op.drop_table('impact_estimates')
    op.drop_constraint(
        'fk_recovery_records_verified_by_users', 'recovery_records', type_='foreignkey'
    )
    op.drop_constraint('ck_recovery_verification_status', 'recovery_records', type_='check')
    op.drop_column('recovery_records', 'verified_at')
    op.drop_column('recovery_records', 'verified_by')
    op.drop_column('recovery_records', 'verification_status')
