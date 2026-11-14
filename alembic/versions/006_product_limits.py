"""Per-product delivery limits and general capacity flag.

Revision ID: 006_product_limits
Revises: 005_customer_unique_credentials
Create Date: 2026-11-14
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "006_product_limits"
down_revision: Union[str, None] = "005_customer_unique_credentials"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("products") as batch:
        batch.add_column(sa.Column("delivery_limit", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column(
                "counts_toward_capacity",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )
    op.execute(
        "UPDATE products SET counts_toward_capacity = false "
        "WHERE name_en = 'Giant Brown-Butter Chocolate Chip Cookie'"
    )


def downgrade() -> None:
    with op.batch_alter_table("products") as batch:
        batch.drop_column("counts_toward_capacity")
        batch.drop_column("delivery_limit")
