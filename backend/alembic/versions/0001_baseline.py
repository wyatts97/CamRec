"""baseline

The initial schema is created by ``Base.metadata.create_all`` in
``app.db.database.init_db`` and then stamped at head. Future schema changes
go in new revisions that build on this one.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-09-23
"""
from typing import Sequence, Union

revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
