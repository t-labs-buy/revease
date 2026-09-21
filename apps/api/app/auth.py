"""Authentication primitives: password hashing, bearer tokens, and the
`CurrentUser` dependency that every private route depends on.

Tokens are stateless HS256 JWTs signed with `Settings.resolved_auth_secret()`.
There is no server-side session table, so "log out" is simply the client
discarding its token; rotating REFRACT_AUTH_SECRET_KEY invalidates every token.
The one per-account revocation is a password change: `set_password` stamps
`User.password_changed_at`, and tokens issued before that instant are refused.
"""

from __future__ import annotations

import base64
import hashlib
import time
from datetime import datetime, timedelta, timezone
from typing import Annotated

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.models import User

ALGORITHM = "HS256"

# auto_error=False so a missing header produces our own 401 shape (with a
# WWW-Authenticate challenge) rather than FastAPI's bare 403.
_bearer = HTTPBearer(auto_error=False)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


# --------------------------------------------------------------------------- #
# passwords
# --------------------------------------------------------------------------- #
def _prehash(password: str) -> bytes:
    """bcrypt silently truncates at 72 bytes, so fold the password into a fixed
    60-byte digest first. Long passphrases then contribute their full entropy."""
    return base64.b64encode(hashlib.sha256(password.encode("utf-8")).digest())


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prehash(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_prehash(password), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False  # malformed/legacy hash — treat as a failed login, never a 500


def set_password(user: User, new_password: str) -> None:
    """Replace the hash and sign every existing session out. The caller commits.

    Tokens carry a fractional-second `iat`, so the login that follows the reset
    is newer than the stamp even when it lands in the same second."""
    user.password_hash = hash_password(new_password)
    user.password_changed_at = time.time()


def normalize_email(email: str) -> str:
    return email.strip().lower()


# --------------------------------------------------------------------------- #
# tokens
# --------------------------------------------------------------------------- #
def create_access_token(user_id: str) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        # Fractional so it orders correctly against `User.password_changed_at`
        # even when the change and the next login land in the same second.
        "iat": now.timestamp(),
        "exp": int((now + timedelta(hours=settings.auth_token_ttl_hours)).timestamp()),
    }
    return jwt.encode(payload, settings.resolved_auth_secret(), algorithm=ALGORITHM)


def token_ttl_seconds() -> int:
    return get_settings().auth_token_ttl_hours * 3600


def decode_access_token(token: str) -> tuple[str, float]:
    """Return (user id, issued-at unix time) from a valid token, else raise 401."""
    try:
        payload = jwt.decode(
            token, get_settings().resolved_auth_secret(), algorithms=[ALGORITHM]
        )
    except jwt.ExpiredSignatureError as e:
        raise _unauthorized("session expired") from e
    except jwt.InvalidTokenError as e:
        raise _unauthorized("invalid token") from e
    user_id = payload.get("sub")
    if not isinstance(user_id, str) or not user_id:
        raise _unauthorized("invalid token")
    issued_at = payload.get("iat")
    # Tokens from before `iat` was set read as issued at epoch 0, so a password
    # change revokes them too.
    return user_id, float(issued_at) if isinstance(issued_at, (int, float)) else 0.0


# --------------------------------------------------------------------------- #
# dependency
# --------------------------------------------------------------------------- #
def get_current_user(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
    db: Session = Depends(get_session),
) -> User:
    if creds is None or not creds.credentials:
        raise _unauthorized("not authenticated")
    user_id, issued_at = decode_access_token(creds.credentials)
    user = db.get(User, user_id)
    if user is None:
        # Token signed for an account that no longer exists.
        raise _unauthorized("account no longer exists")
    if user.password_changed_at is not None and issued_at < user.password_changed_at:
        raise _unauthorized("password was changed — sign in again")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_admin(user: CurrentUser) -> User:
    """Gate for admin-only routes. 403 (not 404) — the routes' existence is not
    a secret, only their data is."""
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin access required")
    return user


AdminUser = Annotated[User, Depends(require_admin)]


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == normalize_email(email)))
