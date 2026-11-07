"""Make customer phone and email unique.

Revision ID: 005_customer_unique_credentials
Revises: 004_users
Create Date: 2026-11-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005_customer_unique_credentials"
down_revision: Union[str, None] = "004_users"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("customers") as batch:
        batch.drop_index("ix_customers_phone")
        batch.create_index("ix_customers_phone", ["phone"], unique=True)
        batch.create_index("ix_customers_email", ["email"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("customers") as batch:
        batch.drop_index("ix_customers_email")
        batch.drop_index("ix_customers_phone")
        batch.create_index("ix_customers_phone", ["phone"], unique=False)
