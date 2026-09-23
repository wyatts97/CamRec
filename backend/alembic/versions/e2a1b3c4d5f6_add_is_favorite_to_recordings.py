"""Add is_favorite to recordings

Revision ID: e2a1b3c4d5f6
Revises: b874435ace8a
Create Date: 2026-06-12 01:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e2a1b3c4d5f6'
down_revision: Union[str, Sequence[str], None] = 'b874435ace8a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('recordings', sa.Column('is_favorite', sa.Boolean(), server_default=sa.text('false'), nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('recordings', 'is_favorite')
