"""create bot_allow_block table

Revision ID: 9d2b3c1a4f10
Revises: 888e7d557311
Create Date: 2026-02-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9d2b3c1a4f10"
down_revision: Union[str, Sequence[str], None] = "888e7d557311"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("bot_allow_block"):
        op.create_table(
            "bot_allow_block",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("instancia", sa.String(length=100), nullable=True),
            sa.Column("numero", sa.String(length=50), nullable=False),
            sa.Column("tipo", sa.String(length=10), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("instancia", "numero", "tipo", name="uq_bot_allow_block_instancia_numero_tipo"),
        )
        op.create_index("ix_bot_allow_block_instancia", "bot_allow_block", ["instancia"], unique=False)
        op.create_index("ix_bot_allow_block_numero", "bot_allow_block", ["numero"], unique=False)
        op.create_index("ix_bot_allow_block_tipo", "bot_allow_block", ["tipo"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_bot_allow_block_tipo", table_name="bot_allow_block")
    op.drop_index("ix_bot_allow_block_numero", table_name="bot_allow_block")
    op.drop_index("ix_bot_allow_block_instancia", table_name="bot_allow_block")
    op.drop_table("bot_allow_block")

