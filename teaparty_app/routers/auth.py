import time

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from teaparty_app.auth import Identity, create_access_token, verify_google_token
from teaparty_app.config import settings
from teaparty_app.db import get_session
from teaparty_app.deps import get_current_user, get_user_by_email
from teaparty_app.models import User
from teaparty_app.schemas import (
    AuthResponse,
    DevLoginRequest,
    GoogleLoginRequest,
    UserPreferencesUpdate,
    UserRead,
)

router = APIRouter(prefix="/api", tags=["auth"])


def _upsert_user(session: Session, identity: Identity) -> User:
    user = get_user_by_email(session, identity.email)
    if user:
        user.name = identity.name
        user.picture = identity.picture
    else:
        user = User(email=identity.email, name=identity.name, picture=identity.picture)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _auth_response(user: User) -> AuthResponse:
    token = create_access_token(user.id)
    return AuthResponse(access_token=token, user=UserRead.model_validate(user))


@router.get("/config")
def read_public_config() -> dict[str, object]:
    return {
        "google_client_id": settings.google_client_id,
        "allow_dev_auth": settings.allow_dev_auth,
    }


@router.post("/auth/google", response_model=AuthResponse)
def login_with_google(payload: GoogleLoginRequest, session: Session = Depends(get_session)) -> AuthResponse:
    identity = verify_google_token(payload.id_token)
    user = _upsert_user(session, identity)
    return _auth_response(user)


@router.post("/auth/dev-login", response_model=AuthResponse)
def login_dev(payload: DevLoginRequest, session: Session = Depends(get_session)) -> AuthResponse:
    if not settings.allow_dev_auth:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dev login disabled")

    identity = Identity(email=str(payload.email), name=payload.name, picture="")
    user = _upsert_user(session, identity)
    return _auth_response(user)


@router.get("/auth/me", response_model=UserRead)
def me(user: User = Depends(get_current_user)) -> UserRead:
    return UserRead.model_validate(user)


@router.patch("/auth/me/preferences", response_model=UserRead)
def update_preferences(
    payload: UserPreferencesUpdate,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> UserRead:
    merged = {**user.preferences, **payload.preferences}
    user.preferences = merged
    session.add(user)
    for attempt in range(3):
        try:
            session.commit()
            break
        except Exception:
            if attempt < 2:
                session.rollback()
                user.preferences = merged
                session.add(user)
                time.sleep(0.15 * (attempt + 1))
            else:
                raise
    session.refresh(user)
    return UserRead.model_validate(user)
