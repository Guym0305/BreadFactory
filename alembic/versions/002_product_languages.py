"""Add Hebrew and English product text.

Revision ID: 002_product_languages
Revises: 001_initial
Create Date: 2026-10-31
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002_product_languages"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("products", sa.Column("name_en", sa.String(length=100), nullable=True))
    op.add_column("products", sa.Column("name_he", sa.String(length=100), nullable=True))
    op.add_column("products", sa.Column("description_en", sa.Text(), nullable=True))
    op.add_column("products", sa.Column("description_he", sa.Text(), nullable=True))
    op.add_column("products", sa.Column("ingredients_en", sa.Text(), nullable=True))
    op.add_column("products", sa.Column("ingredients_he", sa.Text(), nullable=True))
    op.execute(
        "UPDATE products SET name_en = name, description_en = description, ingredients_en = ingredients"
    )


def downgrade() -> None:
    op.drop_column("products", "ingredients_he")
    op.drop_column("products", "ingredients_en")
    op.drop_column("products", "description_he")
    op.drop_column("products", "description_en")
    op.drop_column("products", "name_he")
    op.drop_column("products", "name_en")
