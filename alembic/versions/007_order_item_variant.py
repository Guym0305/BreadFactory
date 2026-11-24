"""Remember a regular or vegan challah on each order line.

Revision ID: 007_order_item_variant
Revises: 006_product_limits
Create Date: 2026-11-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007_order_item_variant"
down_revision: Union[str, None] = "006_product_limits"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("order_items") as batch:
        batch.add_column(sa.Column("variant", sa.String(length=16), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("order_items") as batch:
        batch.drop_column("variant")
