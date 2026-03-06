"""add oculta to bot_clientes

Revision ID: a1c3e5f7b9d2
Revises: 9d2b3c1a4f10
Create Date: 2026-03-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1c3e5f7b9d2"
down_revision: Union[str, Sequence[str], None] = "9d2b3c1a4f10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Adiciona coluna oculta em bot_clientes (false por padrão)."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = [c["name"] for c in inspector.get_columns("bot_clientes")]
    if "oculta" not in cols:
        op.add_column(
            "bot_clientes",
            sa.Column("oculta", sa.Boolean(), nullable=False, server_default="false"),
        )


def downgrade() -> None:
    """Remove coluna oculta de bot_clientes."""
    op.drop_column("bot_clientes", "oculta")
