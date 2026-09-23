"""Add clips table

Revision ID: f3b2c4d5e6f7
Revises: e2a1b3c4d5f6
Create Date: 2026-06-12 02:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3b2c4d5e6f7'
down_revision: Union[str, Sequence[str], None] = 'e2a1b3c4d5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # If the clips table already exists (e.g. from a prior Base.metadata.create_all
    # run before Alembic got to this migration), drop it so Alembic can recreate
    # it properly and stamp the version.
    if 'clips' in inspector.get_table_names():
        op.drop_table('clips')

    op.create_table(
        'clips',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('recording_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=True),
        sa.Column('filename', sa.String(length=512), nullable=False),
        sa.Column('start_time', sa.Integer(), nullable=False),
        sa.Column('end_time', sa.Integer(), nullable=False),
        sa.Column('duration_seconds', sa.Integer(), nullable=True),
        sa.Column('file_size', sa.BigInteger(), nullable=True),
        sa.Column('thumbnail_ready', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('sprite_ready', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['recording_id'], ['recordings.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_clips_id'), 'clips', ['id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_clips_id'), table_name='clips')
    op.drop_table('clips')
