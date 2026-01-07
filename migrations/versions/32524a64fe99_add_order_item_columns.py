"""Add missing columns to OrderItem (Robust)

Revision ID: 32524a64fe99
Revises: f827361a2b3c
Create Date: 2026-01-07 19:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine import reflection

# revision identifiers, used by Alembic.
revision = '32524a64fe99'
down_revision = 'f827361a2b3c'
branch_labels = None
depends_on = None

def upgrade():
    # Use inspector to check for existing columns to avoid DuplicateColumn errors
    conn = op.get_bind()
    insp = reflection.Inspector.from_engine(conn)
    existing_columns = [c['name'] for c in insp.get_columns('order_item')]

    if 'service_assignments' not in existing_columns:
        op.add_column('order_item', sa.Column('service_assignments', sa.Text(), nullable=True))
    
    if 'service_statuses' not in existing_columns:
        op.add_column('order_item', sa.Column('service_statuses', sa.Text(), nullable=True))
        
    if 'service_prices' not in existing_columns:
        op.add_column('order_item', sa.Column('service_prices', sa.Text(), nullable=True))
        
    if 'service_discounts' not in existing_columns:
        op.add_column('order_item', sa.Column('service_discounts', sa.Text(), nullable=True))
        
    if 'vendor_amount' not in existing_columns:
        op.add_column('order_item', sa.Column('vendor_amount', sa.Float(), nullable=True, server_default='0.0'))
        
    if 'is_vendor_paid' not in existing_columns:
        op.add_column('order_item', sa.Column('is_vendor_paid', sa.Boolean(), nullable=True, server_default='false'))
        
    if 'vendor_paid_date' not in existing_columns:
        op.add_column('order_item', sa.Column('vendor_paid_date', sa.DateTime(), nullable=True))

def downgrade():
    # For downgrade, we might drop columns, but this is risky if they existed before.
    # But strictly speaking, downgrade should revert upgrade.
    # Since we conditionally added, we can strictly drop them or check too.
    # For now, standard drop is fine as we assume we want to remove them if we rollback this revision.
    
    conn = op.get_bind()
    insp = reflection.Inspector.from_engine(conn)
    existing_columns = [c['name'] for c in insp.get_columns('order_item')]

    if 'vendor_paid_date' in existing_columns: op.drop_column('order_item', 'vendor_paid_date')
    if 'is_vendor_paid' in existing_columns: op.drop_column('order_item', 'is_vendor_paid')
    if 'vendor_amount' in existing_columns: op.drop_column('order_item', 'vendor_amount')
    if 'service_discounts' in existing_columns: op.drop_column('order_item', 'service_discounts')
    if 'service_prices' in existing_columns: op.drop_column('order_item', 'service_prices')
    if 'service_statuses' in existing_columns: op.drop_column('order_item', 'service_statuses')
    if 'service_assignments' in existing_columns: op.drop_column('order_item', 'service_assignments')
