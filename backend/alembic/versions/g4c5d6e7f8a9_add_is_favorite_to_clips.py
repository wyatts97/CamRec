"""Add is_favorite to clips

Revision ID: g4c5d6e7f8a9
Revises: f3b2c4d5e6f7
Create Date: 2026-06-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'g4c5d6e7f8a9'
down_revision: Union[str, Sequence[str], None] = 'f3b2c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('clips', sa.Column('is_favorite', sa.Boolean(), server_default=sa.text('false'), nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('clips', 'is_favorite')
