"""Add ManualTask CashDeposit and Expense updates

Revision ID: f827361a2b3c
Revises: ec44624941f4
Create Date: 2026-01-03 10:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f827361a2b3c'
down_revision = 'ec44624941f4'
branch_labels = None
depends_on = None


def upgrade():
    # --- Manual Task ---
    op.create_table('manual_task',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=100), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('assigned_to', sa.String(length=100), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=True),
    sa.Column('due_date', sa.DateTime(), nullable=True),
    sa.Column('task_type', sa.String(length=50), nullable=True),
    sa.Column('customer_name', sa.String(length=100), nullable=True),
    sa.Column('mobile', sa.String(length=20), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('completed_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    
    # --- Cash Deposit ---
    op.create_table('cash_deposit',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('amount', sa.Float(), nullable=False),
    sa.Column('deposit_date', sa.Date(), nullable=False),
    sa.Column('reference', sa.String(length=100), nullable=True),
    sa.Column('notes', sa.String(length=255), nullable=True),
    sa.Column('added_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['added_by'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    # --- New Columns ---
    # User
    op.add_column('user', sa.Column('first_login_seen', sa.Boolean(), nullable=True, server_default='false'))
    
    # Order
    op.add_column('order', sa.Column('vendor_amount', sa.Float(), nullable=True))
    
    # Expense
    op.add_column('expense', sa.Column('request_type', sa.String(length=20), nullable=True, server_default='none'))
    op.add_column('expense', sa.Column('request_reason', sa.String(length=255), nullable=True))
    op.add_column('expense', sa.Column('request_data', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('expense', 'request_data')
    op.drop_column('expense', 'request_reason')
    op.drop_column('expense', 'request_type')
    op.drop_column('order', 'vendor_amount')
    op.drop_column('user', 'first_login_seen')
    op.drop_table('cash_deposit')
    op.drop_table('manual_task')
