from __future__ import annotations

import logging

from sqlalchemy import Engine
from sqlmodel import Session, select

from teaparty_app.models import (
    SeedRecord,
    User,
)

logger = logging.getLogger(__name__)

SYSTEM_USER_EMAIL = "system@teaparty.local"
SYSTEM_USER_NAME = "System"


def run_seeds(engine: Engine) -> None:
    try:
        with Session(engine) as session:
            _ensure_system_user(session)
            session.commit()
    except Exception:
        logger.exception("Seed runner failed — app will continue without seeds")


def _ensure_system_user(session: Session) -> User:
    existing_record = session.exec(
        select(SeedRecord).where(SeedRecord.seed_key == "system-user")
    ).first()
    if existing_record:
        user = session.get(User, existing_record.entity_id)
        if user:
            return user

    user = session.exec(
        select(User).where(User.email == SYSTEM_USER_EMAIL)
    ).first()
    if not user:
        user = User(
            email=SYSTEM_USER_EMAIL,
            name=SYSTEM_USER_NAME,
        )
        session.add(user)
        session.flush()

    if existing_record:
        existing_record.entity_id = user.id
        session.add(existing_record)
    else:
        session.add(SeedRecord(
            seed_key="system-user",
            entity_type="user",
            entity_id=user.id,
            seed_version=1,
            checksum="",
        ))
    return user
