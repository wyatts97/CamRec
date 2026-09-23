from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text, BigInteger, UniqueConstraint
from sqlalchemy.orm import relationship

from app.db.database import Base


class User(Base):
    """A watched cam model on one site."""

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("site", "username", name="uq_users_site_username"),)

    id = Column(Integer, primary_key=True, index=True)
    # Which site adapter owns this model (see app/core/sites/registry.py).
    site = Column(String(50), nullable=False, default="flirt4free", index=True)
    username = Column(String(255), index=True, nullable=False)
    display_name = Column(String(255), nullable=True)
    # Site-side numeric id, cached so status/stream lookups skip the name resolve.
    model_id = Column(String(64), nullable=True)
    # Last observed room state: public, private, offline, not_found.
    room_state = Column(String(20), nullable=True)
    is_monitoring = Column(Boolean, default=False)
    # True only while the room is public (recordable).
    is_live = Column(Boolean, default=False)
    is_on_watchlist = Column(Boolean, default=True)
    last_checked = Column(DateTime, nullable=True)
    profile_pic_url = Column(String(512), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Cascade so deleting a user removes their recordings rather than
    # violating the recordings.user_id foreign key.
    recordings = relationship(
        "Recording", back_populates="user", cascade="all, delete-orphan"
    )


class Recording(Base):
    __tablename__ = "recordings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    filename = Column(String(512), nullable=False)
    status = Column(String(50), default="pending")  # pending, recording, processing, completed, failed, stopped
    mode = Column(String(50), default="manual")  # manual, automatic
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    file_size = Column(BigInteger, nullable=True)
    error_message = Column(Text, nullable=True)
    thumbnail_ready = Column(Boolean, default=False)
    sprite_ready = Column(Boolean, default=False)
    is_favorite = Column(Boolean, default=False)
    # Cached corruption state set at finalize/repair time so list endpoints
    # don't shell out to ffprobe per row. NULL = not yet determined.
    is_corrupt = Column(Boolean, nullable=True)
    # Post-recording AV1 compression (see core/compression_service.py):
    # NULL (never queued), pending, processing, done, skipped, failed.
    compress_status = Column(String(20), nullable=True)
    compress_error = Column(Text, nullable=True)
    # Size of the original H.264 file, set once the compressed file replaces it.
    original_size = Column(BigInteger, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="recordings")
    # Clips deliberately OUTLIVE their recording: deleting a recording frees
    # the (large) source file while keeping the (small) clips the user cut
    # from it. The database nulls Clip.recording_id via ON DELETE SET NULL,
    # so passive_deletes hands that to the DB instead of having SQLAlchemy
    # load and update every child first.
    clips = relationship(
        "Clip", back_populates="recording", passive_deletes=True
    )


class Clip(Base):
    __tablename__ = "clips"

    id = Column(Integer, primary_key=True, index=True)
    # Nullable, and nulled rather than cascaded when the recording goes: a clip
    # is an independent artefact once it has been cut.
    recording_id = Column(
        Integer, ForeignKey("recordings.id", ondelete="SET NULL"), nullable=True
    )
    # Denormalised so a clip still knows who it is of after its recording is
    # deleted. Without this the username could only be reached through the
    # recording, and orphaned clips would render as "unknown".
    username = Column(String(255), nullable=True, index=True)
    title = Column(String(255), nullable=True)
    filename = Column(String(512), nullable=False)
    start_time = Column(Integer, nullable=False)
    end_time = Column(Integer, nullable=False)
    duration_seconds = Column(Integer, nullable=True)
    file_size = Column(BigInteger, nullable=True)
    thumbnail_ready = Column(Boolean, default=False)
    sprite_ready = Column(Boolean, default=False)
    is_favorite = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    recording = relationship("Recording", back_populates="clips")
