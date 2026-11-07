"""Store how the order will be charged.

Revision ID: 003_payment_method
Revises: 002_product_languages
Create Date: 2026-11-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003_payment_method"
down_revision: Union[str, None] = "002_product_languages"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("payment_method", sa.String(length=32), nullable=True))
    op.add_column("orders", sa.Column("payment_other", sa.String(length=120), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "payment_other")
    op.drop_column("orders", "payment_method")
