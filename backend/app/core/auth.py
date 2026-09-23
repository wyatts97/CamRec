"""Single-password session authentication.

This app is intended to be reachable from the internet, so every route outside
of ``/api/health`` and the login endpoints requires a valid session cookie.

Design notes:
  * One shared password, because this is a single-operator self-hosted tool.
    The password is stored only as a scrypt hash in ``data/auth.json``.
  * Sessions are stateless signed tokens (HMAC-SHA256 over ``expiry:nonce``),
    so restarts do not log the user out as long as the signing secret persists.
  * If no password is configured on first boot we generate one, persist its
    hash, and log the plaintext exactly once.  Auth is never silently off.

Only stdlib crypto is used (``hashlib.scrypt``/``hmac``) to avoid pulling in
passlib for a single hash.
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from pathlib import Path

from fastapi import Depends, HTTPException, Request, Response, status

from app.config import settings

logger = logging.getLogger(__name__)

SESSION_COOKIE = "camsuite_session"
SESSION_TTL_SECONDS = 30 * 24 * 3600  # 30 days

# scrypt parameters — deliberately costly, this runs once per login.
_SCRYPT_N = 2 ** 15
_SCRYPT_R = 8
_SCRYPT_P = 1
# OpenSSL enforces a 32 MiB default cap and these parameters need exactly
# 128 * N * r = 32 MiB, which trips it.  Raise the ceiling explicitly.
_SCRYPT_MAXMEM = 128 * _SCRYPT_N * _SCRYPT_R * 2


def _auth_file() -> Path:
    return Path(settings.DATA_DIR) / "auth.json"


def _hash_password(password: str, salt: bytes) -> str:
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        maxmem=_SCRYPT_MAXMEM,
        dklen=32,
    )
    return base64.b64encode(digest).decode("ascii")


class AuthState:
    """Loads (or provisions) the password hash and the session signing secret."""

    def __init__(self) -> None:
        self._salt: bytes = b""
        self._hash: str = ""
        self._secret: bytes = b""
        self._load()

    def _load(self) -> None:
        path = _auth_file()
        data: dict = {}
        if path.exists():
            try:
                data = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                logger.exception("Could not read %s; re-provisioning credentials", path)
                data = {}

        # Read through Settings, not os.environ, so an APP_PASSWORD set in a
        # .env file actually applies -- pydantic-settings loads .env into the
        # Settings object but never exports it to the process environment.
        env_password = settings.APP_PASSWORD
        stored = bool(data.get("password_hash") and data.get("salt"))

        # APP_PASSWORD *seeds* the credential; it does not override an existing
        # one on every boot. Overriding meant a container restart silently
        # reverted any password the user had since changed. FORCE_RESET is the
        # deliberate break-glass path.
        force_reset = os.environ.get("APP_PASSWORD_FORCE_RESET", "").lower() in ("1", "true", "yes")

        if env_password and (not stored or force_reset):
            self._salt = secrets.token_bytes(16)
            self._hash = _hash_password(env_password, self._salt)
            if force_reset:
                logger.warning("APP_PASSWORD_FORCE_RESET set; login password reset from environment.")
        elif stored:
            self._salt = base64.b64decode(data["salt"])
            self._hash = data["password_hash"]
        else:
            generated = secrets.token_urlsafe(18)
            self._salt = secrets.token_bytes(16)
            self._hash = _hash_password(generated, self._salt)
            logger.critical(
                "=" * 68
                + "\nNo APP_PASSWORD set. Generated an initial login password:\n\n"
                f"    {generated}\n\n"
                "Store it now — it will not be shown again. Set APP_PASSWORD in\n"
                "your environment to choose your own.\n" + "=" * 68
            )

        self._secret = base64.b64decode(data["secret"]) if data.get("secret") else secrets.token_bytes(32)
        self._persist(data)

    def _persist(self, previous: dict) -> None:
        payload = {
            "salt": base64.b64encode(self._salt).decode("ascii"),
            "password_hash": self._hash,
            "secret": base64.b64encode(self._secret).decode("ascii"),
        }
        if payload == previous:
            return
        path = _auth_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write so a crash mid-write cannot lock the operator out.
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2))
        os.replace(tmp, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            # Windows / some volume mounts do not support chmod; not fatal.
            pass

    def verify_password(self, password: str) -> bool:
        candidate = _hash_password(password, self._salt)
        return hmac.compare_digest(candidate, self._hash)

    def issue_token(self) -> str:
        expiry = int(time.time()) + SESSION_TTL_SECONDS
        payload = f"{expiry}:{secrets.token_urlsafe(12)}"
        signature = hmac.new(self._secret, payload.encode(), hashlib.sha256).hexdigest()
        return f"{payload}:{signature}"

    def verify_token(self, token: str) -> bool:
        try:
            expiry_raw, nonce, signature = token.split(":", 2)
        except ValueError:
            return False
        payload = f"{expiry_raw}:{nonce}"
        expected = hmac.new(self._secret, payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return False
        try:
            return int(expiry_raw) > time.time()
        except ValueError:
            return False

    def rotate_secret(self) -> None:
        """Invalidate every outstanding session (used on logout-everywhere)."""
        self._secret = secrets.token_bytes(32)
        self._persist({})


_state: AuthState | None = None


def auth_state() -> AuthState:
    global _state
    if _state is None:
        _state = AuthState()
    return _state


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=settings.COOKIE_SECURE,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def require_auth(request: Request) -> None:
    """Router-level dependency. Raises 401 unless a valid session is present."""
    if not settings.AUTH_ENABLED:
        return
    token = request.cookies.get(SESSION_COOKIE)
    if not token or not auth_state().verify_token(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )


AuthDep = Depends(require_auth)
