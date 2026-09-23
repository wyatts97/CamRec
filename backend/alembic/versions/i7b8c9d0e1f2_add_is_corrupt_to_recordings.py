"""add is_corrupt to recordings

Revision ID: i7b8c9d0e1f2
Revises: h6a7b8c9d0e1
Create Date: 2026-07-06 03:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'i7b8c9d0e1f2'
down_revision: Union[str, Sequence[str], None] = 'h6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('recordings', sa.Column('is_corrupt', sa.Boolean(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('recordings', 'is_corrupt')
