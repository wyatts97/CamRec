"""Background ZIP export jobs.

Replaces the old blocking batch-download endpoints, which built the whole
archive inside the request and left the temp file behind.
"""
import logging
from pathlib import Path
from typing import List, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.core.export_service import export_service
from app.core.media_utils import clip_directory, recording_path
from app.db.database import get_db
from app.db.models import Clip, Recording

logger = logging.getLogger("tikrec.exports")

router = APIRouter(prefix="/exports", tags=["exports"])


def _recording_files(db: Session, ids: List[int] | None) -> list[tuple[Path, str]]:
    query = db.query(Recording).filter(
        Recording.status.in_(("completed", "stopped"))
    )
    if ids:
        query = query.filter(Recording.id.in_(ids))
    return [(recording_path(r.filename), r.filename) for r in query.all()]


def _clip_files(db: Session, ids: List[int] | None) -> list[tuple[Path, str]]:
    query = db.query(Clip)
    if ids:
        query = query.filter(Clip.id.in_(ids))
    out = []
    for clip in query.all():
        out.append((clip_directory() / clip.filename, clip.filename))
    return out


@router.post("", status_code=status.HTTP_202_ACCEPTED)
def create_export(
    kind: Literal["recordings", "clips"] = Body(...),
    ids: List[int] | None = Body(default=None),
    db: Session = Depends(get_db),
):
    """Queue a ZIP export. Omit `ids` to export everything of that kind.

    Returns immediately with a job id; poll GET /exports/{id} for progress.
    """
    files = _recording_files(db, ids) if kind == "recordings" else _clip_files(db, ids)
    if not files:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No {kind} found to export",
        )

    from time import strftime
    filename = f"{kind}_{strftime('%Y%m%d_%H%M%S')}.zip"
    try:
        job = export_service.create(files, filename)
    except ValueError as exc:
        # Nothing on disk, or not enough free space -- both are the caller's
        # problem to see, not a 500.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return job.as_dict()


@router.get("/{job_id}")
def get_export(job_id: str):
    job = export_service.get(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Export not found")
    return job.as_dict()


@router.delete("/{job_id}")
def cancel_export(job_id: str):
    job = export_service.get(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Export not found")
    cancelled = export_service.cancel(job_id)
    export_service.discard(job_id)
    return {"cancelled": cancelled}


@router.get("/{job_id}/download")
def download_export(job_id: str):
    job = export_service.get(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Export not found")
    if job.status != "ready" or not job.path:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Export is {job.status}, not ready",
        )
    # Delete the archive once the response has been sent, rather than leaving
    # it for the OS temp sweeper.
    return FileResponse(
        path=job.path,
        filename=job.filename,
        media_type="application/zip",
        background=BackgroundTask(export_service.discard, job_id),
    )
