"""Let clips outlive their source recording

Deleting a recording previously either failed outright (once foreign keys were
enforced) or silently orphaned clip rows. Neither is what we want: a clip is an
independent artefact, and deleting the large source file should not take the
small clips cut from it.

Two changes:
  * clips.recording_id becomes nullable with ON DELETE SET NULL, so deleting a
    recording detaches its clips instead of deleting or breaking them.
  * clips.username is denormalised onto the row, because once the recording is
    gone the username can no longer be reached through the relationship.

SQLite cannot ALTER a column's nullability or its foreign key, so this runs
inside batch_alter_table, which rebuilds the table and copies the data.

Revision ID: j8c9d0e1f2a3
Revises: i7b8c9d0e1f2
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'j8c9d0e1f2a3'
down_revision: Union[str, Sequence[str], None] = 'i7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    if not _has_column("clips", "username"):
        op.add_column("clips", sa.Column("username", sa.String(255), nullable=True))

    # Backfill from the existing relationship before anything can be detached.
    op.execute(
        """
        UPDATE clips
           SET username = (
               SELECT users.username
                 FROM recordings
                 JOIN users ON users.id = recordings.user_id
                WHERE recordings.id = clips.recording_id
           )
         WHERE username IS NULL
        """
    )

    # Rebuild the table so recording_id can become nullable and gain
    # ON DELETE SET NULL.
    #
    # copy_from is given explicitly rather than letting alembic reflect the
    # table: reflection carries the original implicit foreign key along, so
    # create_foreign_key would *append* a second one and the rebuilt table
    # would end up with two constraints on the same column -- one NO ACTION,
    # one SET NULL. Describing the table without a foreign key means the only
    # one on the new table is the one created below.
    clips_without_fk = sa.Table(
        "clips",
        sa.MetaData(),
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("recording_id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(255), nullable=True),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("start_time", sa.Integer(), nullable=False),
        sa.Column("end_time", sa.Integer(), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("thumbnail_ready", sa.Boolean(), nullable=True),
        sa.Column("sprite_ready", sa.Boolean(), nullable=True),
        sa.Column("is_favorite", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )

    with op.batch_alter_table(
        "clips", schema=None, copy_from=clips_without_fk
    ) as batch_op:
        batch_op.alter_column(
            "recording_id", existing_type=sa.Integer(), nullable=True
        )
        batch_op.create_foreign_key(
            "fk_clips_recording_id",
            "recordings",
            ["recording_id"],
            ["id"],
            ondelete="SET NULL",
        )

    # Created after the rebuild, not before: batch_alter_table recreates the
    # table from copy_from and would drop an index it does not know about.
    op.create_index("ix_clips_username", "clips", ["username"])


def downgrade() -> None:
    # Clips detached from a recording cannot satisfy a NOT NULL foreign key,
    # so they are removed on the way down.
    op.execute("DELETE FROM clips WHERE recording_id IS NULL")

    with op.batch_alter_table("clips", schema=None) as batch_op:
        batch_op.drop_constraint("fk_clips_recording_id", type_="foreignkey")
        batch_op.alter_column(
            "recording_id", existing_type=sa.Integer(), nullable=False
        )
        batch_op.create_foreign_key(
            "fk_clips_recording_id", "recordings", ["recording_id"], ["id"]
        )

    if _has_column("clips", "username"):
        # The rebuild above drops the index with the old table, so only try
        # to drop it if it is still there.
        inspector = sa.inspect(op.get_bind())
        if "ix_clips_username" in {i["name"] for i in inspector.get_indexes("clips")}:
            op.drop_index("ix_clips_username", table_name="clips")
        op.drop_column("clips", "username")
