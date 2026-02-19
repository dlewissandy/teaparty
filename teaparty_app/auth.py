"""JWT token creation/verification and Google OAuth ID-token validation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from jose import JWTError, jwt

from teaparty_app.config import settings


@dataclass
class Identity:
    email: str
    name: str
    picture: str


ALGORITHM = "HS256"


def create_access_token(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.session_expires_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.app_secret, algorithm=ALGORITHM)


def decode_access_token(token: str) -> str:
    try:
        payload = jwt.decode(token, settings.app_secret, algorithms=[ALGORITHM])
    except JWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session token") from exc

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token missing user id")
    return user_id


def verify_google_token(raw_id_token: str) -> Identity:
    if not settings.google_client_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="TEAPARTY_GOOGLE_CLIENT_ID is not configured",
        )

    try:
        payload = id_token.verify_oauth2_token(
            raw_id_token,
            google_requests.Request(),
            settings.google_client_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Google token verification failed") from exc

    if not payload.get("email_verified"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Google account email is not verified")

    email = payload.get("email")
    if not email:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Google token missing email")

    return Identity(
        email=email,
        name=payload.get("name", email.split("@")[0]),
        picture=payload.get("picture", ""),
    )
