import os
from dataclasses import dataclass
import zipfile
import shutil
from datetime import datetime, timedelta
from pathlib import Path


from app.config import settings
from app.core.settings_store import settings_store
from app.core.media_utils import all_thumbnail_paths, recording_path
from app.db.database import get_session
from app.db.models import Recording


@dataclass(frozen=True)
class OldRecording:
    """A recording selected for cleanup, safe to pass between sessions."""
    id: int
    filename: str


class CleanupService:
    """Service for auto-cleaning old recordings."""
    
    BACKUPS_DIR = Path(settings.DATA_DIR) / "backups"
    
    def __init__(self):
        self.BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    
    def get_config(self) -> dict:
        """Get current auto-cleanup configuration."""
        return settings_store.get("auto_cleanup", {
            "enabled": False,
            "days": 7,
            "action": "delete"
        })
    
    def get_old_recordings(self, days: int) -> list["OldRecording"]:
        """Recordings older than `days`, as plain records.

        Deliberately NOT live ORM instances: the session closes when this
        returns, so callers used to hand detached objects to a *different*
        session's db.delete(), which triggers surprise refresh queries and can
        raise DetachedInstanceError.  Callers re-query by id instead.
        """
        cutoff = datetime.utcnow() - timedelta(days=days)
        with get_session() as db:
            rows = db.query(Recording.id, Recording.filename).filter(
                Recording.status.in_(["completed", "stopped", "failed"]),
                Recording.created_at < cutoff
            ).all()
        return [OldRecording(id=r.id, filename=r.filename) for r in rows]

    def delete_recording(self, recording) -> bool:
        """Delete all on-disk assets for a recording (video, thumbnail, sprite sheet, sprite VTT).

        Accepts anything with a `filename` -- an ORM Recording or an
        OldRecording record.
        """
        file_path = recording_path(recording.filename)

        assets = [
            file_path,
            *all_thumbnail_paths(file_path),
            file_path.with_name(file_path.stem + "_sprite.jpg"),
            file_path.with_name(file_path.stem + "_sprite.vtt"),
        ]

        deleted = False
        for path in assets:
            if path.exists():
                try:
                    os.remove(path)
                    if path == file_path:
                        deleted = True
                except OSError:
                    pass

        return deleted
    
    def compress_recordings(self, recordings: list[Recording]) -> str | None:
        """Compress recordings into a ZIP file in the backups folder."""
        if not recordings:
            return None
        
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        zip_filename = f"backup_{timestamp}.zip"
        zip_path = self.BACKUPS_DIR / zip_filename
        
        try:
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for recording in recordings:
                    file_path = recording_path(recording.filename)
                    if file_path.exists():
                        zf.write(file_path, recording.filename)
            
            return str(zip_path)
        except Exception:
            if zip_path.exists():
                os.remove(zip_path)
            return None
    
    def run_cleanup(self) -> dict:
        """Run the cleanup process based on current settings."""
        config = self.get_config()
        
        if not config.get("enabled", False):
            return {"status": "disabled", "deleted": 0, "compressed": 0}
        
        days = config.get("days", 7)
        action = config.get("action", "delete")
        
        recordings = self.get_old_recordings(days)
        
        if not recordings:
            return {"status": "no_old_recordings", "deleted": 0, "compressed": 0}
        
        result = {"status": "completed", "deleted": 0, "compressed": 0}
        
        if action == "compress":
            zip_path = self.compress_recordings(recordings)
            if not zip_path:
                return result
            result["compressed"] = len(recordings)
            result["backup_file"] = zip_path

        for record in recordings:
            if self.delete_recording(record):
                result["deleted"] += 1

        # Re-query inside the session that performs the delete, rather than
        # deleting instances loaded by an already-closed session.
        ids = [r.id for r in recordings]
        with get_session() as db:
            for chunk_start in range(0, len(ids), 500):
                chunk = ids[chunk_start:chunk_start + 500]
                for rec in db.query(Recording).filter(Recording.id.in_(chunk)).all():
                    db.delete(rec)
            db.commit()

        return result
    
    def get_cleanup_stats(self) -> dict:
        """Get statistics about what would be cleaned up."""
        config = self.get_config()
        days = config.get("days", 7)
        
        recordings = self.get_old_recordings(days)
        total_size = 0
        
        for recording in recordings:
            file_path = recording_path(recording.filename)
            if file_path.exists():
                total_size += file_path.stat().st_size
        
        return {
            "count": len(recordings),
            "total_size": total_size,
            "days": days
        }


cleanup_service = CleanupService()
