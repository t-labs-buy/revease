"""Accounts: register, log in, and read the current user.

Only /login issues a token — registering creates the account and nothing more.
Logging out is client-side (discard the token), so there is no /logout route.

There is no "forgot password" email flow (this deployment has no email
transport). A user who is locked out asks an admin, who sets a new password from
the Admin → Users page (`POST /admin/users/{id}/password` in routers/admin.py).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import (
    CurrentUser,
    create_access_token,
    get_user_by_email,
    hash_password,
    normalize_email,
    token_ttl_seconds,
    verify_password,
)
from app.config import get_settings
from app.db import get_session
from app.models import User
from app.schemas import LoginIn, RegisterIn, TokenOut, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


def _bootstrap_role(email: str) -> str:
    """Emails listed in REFRACT_ADMIN_EMAILS start (and stay) admin; everyone
    else starts as a regular user and can be promoted from the Admin UI."""
    return "admin" if email in get_settings().admin_email_set() else "user"


def _token_response(user: User) -> TokenOut:
    return TokenOut(
        access_token=create_access_token(user.id),
        expires_in=token_ttl_seconds(),
        user=UserOut.model_validate(user),
    )


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterIn, db: Session = Depends(get_session)) -> User:
    """Create an account. Deliberately does NOT return a token: registering does
    not sign you in, so the client sends the new user to the login screen to
    enter their password once more.

    New spaces start with the sample skill + onboarding articles so Skills and the
    Knowledge Base aren't empty on first visit."""
    email = normalize_email(payload.email)
    if get_user_by_email(db, email) is not None:
        raise HTTPException(status_code=409, detail="an account with this email already exists")

    user = User(
        email=email,
        name=payload.name.strip(),
        password_hash=hash_password(payload.password),
        role=_bootstrap_role(email),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    from app.seed import seed_for_user

    seed_for_user(db, user.id)
    return user


@router.post("/login", response_model=TokenOut)
def login(payload: LoginIn, db: Session = Depends(get_session)) -> TokenOut:
    user = get_user_by_email(db, payload.email)
    # One message for both "no such account" and "wrong password": telling them
    # apart would let anyone probe which emails are registered.
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    # Accounts that predate the env listing (or the role column) get promoted on
    # their next login, so the bootstrap admin never needs a manual DB edit.
    if not user.is_admin and _bootstrap_role(user.email) == "admin":
        user.role = "admin"
        db.commit()
        db.refresh(user)
    return _token_response(user)


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> User:
    """Validate the stored token and return its account (used on app boot)."""
    return user
