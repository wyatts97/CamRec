"""Global library search across transcripts and live chat/gift events.

Returns matches with jump-to-timestamp offsets so the frontend can deep-link
into the player at the relevant moment.
"""
import re

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.db.database import get_db
from app.db.models import Recording, LiveEvent, User

router = APIRouter(prefix="/search", tags=["search"])

# Matches transcript lines like "[00:01:23 --> 00:01:25] some text" or "[01:23] text"
_TS_LINE = re.compile(r"^\[(\d{2}):(\d{2})(?::(\d{2}))?(?:\s*-->\s*[\d:]+)?\]\s*(.*)$")


def _line_to_seconds(h: str, m: str, s: str | None) -> int:
    if s is None:
        # Two-part timestamp is MM:SS
        return int(h) * 60 + int(m)
    return int(h) * 3600 + int(m) * 60 + int(s)


def _transcript_matches(text: str, query: str, max_matches: int = 5) -> list[dict]:
    """Find matching transcript lines and their start offset in seconds."""
    q = query.lower()
    out: list[dict] = []
    for line in text.splitlines():
        if q not in line.lower():
            continue
        m = _TS_LINE.match(line.strip())
        if m:
            seconds = _line_to_seconds(m.group(1), m.group(2), m.group(3))
            snippet = m.group(4).strip()
        else:
            seconds = 0
            snippet = line.strip()
        out.append({"offset_seconds": seconds, "snippet": snippet[:200]})
        if len(out) >= max_matches:
            break
    return out


@router.get("")
def global_search(q: str, limit: int = 50, db: Session = Depends(get_db)):
    """Search transcripts and live events for *q*.

    Returns ``{transcripts: [...], events: [...]}`` where each result carries
    a recording id, username, and an offset to seek to.
    """
    query = (q or "").strip()
    if len(query) < 2:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Query too short")

    limit = max(1, min(limit, 200))
    like = f"%{query}%"

    # --- Transcript matches ---
    transcript_recs = (
        db.query(Recording)
        .options(joinedload(Recording.user))
        .filter(
            Recording.transcript_status == "done",
            func.lower(Recording.transcript_text).contains(query.lower()),
        )
        .limit(limit)
        .all()
    )
    transcripts = []
    for rec in transcript_recs:
        matches = _transcript_matches(rec.transcript_text or "", query)
        if not matches:
            continue
        transcripts.append({
            "recording_id": rec.id,
            "username": rec.user.username if rec.user else "unknown",
            "match_count": len(matches),
            "matches": matches,
        })

    # --- Live chat / gift matches ---
    event_rows = (
        db.query(LiveEvent, User.username)
        .join(Recording, LiveEvent.recording_id == Recording.id)
        .join(User, Recording.user_id == User.id)
        .filter(
            LiveEvent.user_nickname.ilike(like)
            | LiveEvent.content.ilike(like)
            | LiveEvent.gift_name.ilike(like)
        )
        .order_by(LiveEvent.recording_id.desc(), LiveEvent.offset_seconds.asc())
        .limit(limit)
        .all()
    )
    events = [
        {
            "id": ev.id,
            "recording_id": ev.recording_id,
            "username": uname,
            "offset_seconds": ev.offset_seconds,
            "event_type": ev.event_type,
            "user_nickname": ev.user_nickname,
            "content": ev.content,
            "gift_name": ev.gift_name,
        }
        for ev, uname in event_rows
    ]

    return {
        "query": query,
        "transcripts": transcripts,
        "events": events,
        "transcript_count": len(transcripts),
        "event_count": len(events),
    }
