"""recording compression columns

Revision ID: 0002_recording_compression
Revises: 0001_baseline
Create Date: 2026-09-23
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_recording_compression"
down_revision: Union[str, None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("recordings") as batch:
        batch.add_column(sa.Column("compress_status", sa.String(length=20), nullable=True))
        batch.add_column(sa.Column("compress_error", sa.Text(), nullable=True))
        batch.add_column(sa.Column("original_size", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("recordings") as batch:
        batch.drop_column("original_size")
        batch.drop_column("compress_error")
        batch.drop_column("compress_status")
