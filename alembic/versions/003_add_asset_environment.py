"""Add environment field to assets.

Revision ID: 003
Revises: 002
Create Date: 2025-12-21 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None

def upgrade():
    # 1. Add environment column with default 'production'
    op.add_column('assets', sa.Column('environment', sa.String(length=50), nullable=False, server_default='production'))
    # 2. Add index on environment
    op.create_index(op.f('ix_assets_environment'), 'assets', ['environment'], unique=False)
    # 3. Drop old unique constraint on fqn
    # For SQLite, we might need a batch operation, but for Postgres it's standard.
    # Alembic handles many of these differences.
    with op.batch_alter_table('assets') as batch_op:
        batch_op.drop_constraint('assets_fqn_key', type_='unique')
        # 4. Add new composite unique constraint
        batch_op.create_unique_constraint('uq_asset_fqn_environment', ['fqn', 'environment'])

def downgrade():
    with op.batch_alter_table('assets') as batch_op:
        batch_op.drop_constraint('uq_asset_fqn_environment', type_='unique')
        batch_op.create_unique_constraint('assets_fqn_key', ['fqn'])
    op.drop_index(op.f('ix_assets_environment'), table_name='assets')
    op.drop_column('assets', 'environment')
