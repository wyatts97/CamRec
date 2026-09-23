import logging
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)


class UserInfoService:
    """Fetch TikTok user profile info using the bundled recorder API."""

    AVATARS_DIR = Path(settings.DATA_DIR) / "avatars"

    def __init__(self):
        self.AVATARS_DIR.mkdir(parents=True, exist_ok=True)
        # Delayed import to avoid circular dependency at module load time
        from app.core.unified_avatar_service import unified_avatar_service
        self._avatar_service = unified_avatar_service

    def fetch_user_info(self, username: str) -> dict:
        """
        Use the recorder API to fetch user profile info.
        Returns a dict with: display_name, bio, follower_count, avatar_url.
        Returns an empty dict on any error so callers can degrade gracefully.
        """
        result: dict = {}
        try:
            from app.core.recorder_service import recorder_service
            room_id = recorder_service.get_room_id(username)
            if not room_id:
                return result

            api = recorder_service.get_api()
            data = api.http_client.get(
                f"https://webcast.tiktok.com/webcast/room/info/?aid=1988&room_id={room_id}"
            ).json()

            owner = data.get("data", {}).get("owner", {})
            follow_info = owner.get("follow_info", {})

            result["display_name"] = owner.get("nickname")
            result["bio"] = owner.get("bio_description")
            result["follower_count"] = follow_info.get("follower_count")
            result["avatar_url"] = (
                owner.get("avatar_large", {}).get("url_list", [None])[0]
                or owner.get("avatar_medium", {}).get("url_list", [None])[0]
                or owner.get("avatar_thumb", {}).get("url_list", [None])[0]
            )
        except Exception as exc:
            logger.warning(f"Recorder profile fetch failed for @{username}: {exc}")

        return result

    def update_user_profile(self, db_user, db) -> None:
        """
        Fetch profile info from TikTok and persist it on ``db_user``.
        Also fetches and caches the avatar if available.
        Commits the session when done.
        """
        info = self.fetch_user_info(db_user.username)
        if info.get("display_name"):
            db_user.display_name = info["display_name"]
        if info.get("bio") is not None:
            db_user.bio = info["bio"]
        if info.get("follower_count") is not None:
            db_user.follower_count = info["follower_count"]

        # Cache avatar from recorder API result if available
        avatar_url = info.get("avatar_url")
        if avatar_url:
            try:
                cached = self._avatar_service.download_and_cache(db_user.username, avatar_url)
                if cached and not db_user.profile_pic_url:
                    db_user.profile_pic_url = f"/api/users/{db_user.id}/avatar"
            except Exception as exc:
                logger.warning(f"Avatar cache failed for @{db_user.username}: {exc}")

        db.commit()

    def update_user_profile_async(self, user_id: int) -> None:
        """Fire-and-forget: update profile in the background thread pool."""
        from app.db.database import get_session, run_background

        def _run():
            from app.db.models import User
            with get_session() as db:
                user = db.query(User).filter(User.id == user_id).first()
                if user:
                    self.update_user_profile(user, db)

        run_background(_run)


user_info_service = UserInfoService()
