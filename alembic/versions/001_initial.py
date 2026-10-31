"""Initial bakery schema.

Revision ID: 001_initial
Revises:
Create Date: 2026-10-31
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("image_url", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("ingredients", sa.Text(), nullable=True),
        sa.Column("fermentation_hours", sa.Integer(), nullable=True, server_default="30"),
    )
    op.create_table(
        "customers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("full_name", sa.String(length=100), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("email", sa.String(length=100), nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_customers_phone", "customers", ["phone"])
    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("order_number", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="PENDING_PAYMENT"),
        sa.Column("delivery_date", sa.DateTime(), nullable=False),
        sa.Column("total_amount", sa.Float(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("payment_url", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_orders_customer_id", "orders", ["customer_id"])
    op.create_index("ix_orders_order_number", "orders", ["order_number"], unique=True)
    op.create_index("ix_orders_delivery_date", "orders", ["delivery_date"])
    op.create_table(
        "order_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Float(), nullable=False),
    )
    op.create_index("ix_order_items_order_id", "order_items", ["order_id"])
    op.create_index("ix_order_items_product_id", "order_items", ["product_id"])
    op.create_table(
        "payment_transactions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("grow_transaction_id", sa.String(length=100), nullable=False),
        sa.Column("amount_charged", sa.Float(), nullable=False),
        sa.Column("card_mask", sa.String(length=20), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("raw_response", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_payment_transactions_order_id", "payment_transactions", ["order_id"], unique=True)
    op.create_index(
        "ix_payment_transactions_grow_transaction_id",
        "payment_transactions",
        ["grow_transaction_id"],
    )


def downgrade() -> None:
    op.drop_table("payment_transactions")
    op.drop_table("order_items")
    op.drop_table("orders")
    op.drop_table("customers")
    op.drop_table("products")
