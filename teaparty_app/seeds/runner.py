from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import yaml
from sqlalchemy import Engine
from sqlmodel import Session, select

from teaparty_app.models import (
    Agent,
    Membership,
    Organization,
    SeedRecord,
    User,
    Workgroup,
    new_id,
)

logger = logging.getLogger(__name__)

_SEEDS_DIR = Path(__file__).parent
_TEMPLATES_DIR = _SEEDS_DIR / "templates"
_DEFAULTS_DIR = _SEEDS_DIR / "defaults"

SYSTEM_USER_EMAIL = "system@teaparty.local"
SYSTEM_USER_NAME = "System"


SEED_ORGANIZATION_NAME = "Teaparty"


def run_seeds(engine: Engine) -> None:
    try:
        with Session(engine) as session:
            system_user = _ensure_system_user(session)
            seed_org = _ensure_seed_organization(session, system_user)
            _seed_default_workgroups(session, system_user, seed_org)
            session.commit()
    except Exception:
        logger.exception("Seed runner failed — app will continue without seeds")


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


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


def _ensure_seed_organization(session: Session, system_user: User) -> Organization:
    existing_record = session.exec(
        select(SeedRecord).where(SeedRecord.seed_key == "seed-organization")
    ).first()
    if existing_record:
        org = session.get(Organization, existing_record.entity_id)
        if org:
            return org

    org = session.exec(
        select(Organization).where(Organization.name == SEED_ORGANIZATION_NAME)
    ).first()
    if not org:
        org = Organization(name=SEED_ORGANIZATION_NAME, description="Default organization for seed workgroups", owner_id=system_user.id)
        session.add(org)
        session.flush()

    if existing_record:
        existing_record.entity_id = org.id
        session.add(existing_record)
    else:
        session.add(SeedRecord(
            seed_key="seed-organization",
            entity_type="organization",
            entity_id=org.id,
            seed_version=1,
            checksum="",
        ))
    return org


def _load_yaml(path: Path) -> dict:
    with open(path) as fh:
        return yaml.safe_load(fh) or {}


def _seed_default_workgroups(session: Session, system_user: User, seed_org: Organization) -> None:
    defaults_path = _DEFAULTS_DIR / "workgroups.yaml"
    if not defaults_path.exists():
        logger.warning("No defaults/workgroups.yaml found — skipping default workgroup seeding")
        return

    defaults = _load_yaml(defaults_path)
    version = defaults.get("version", 1)
    workgroup_specs = defaults.get("workgroups", [])

    for spec in workgroup_specs:
        seed_key = spec.get("seed_key")
        if not seed_key:
            continue

        template_key = spec.get("template")
        if not template_key:
            continue

        template_path = _TEMPLATES_DIR / f"{template_key}.yaml"
        if not template_path.exists():
            logger.warning("Template %s not found for seed %s — skipping", template_key, seed_key)
            continue

        template_content = template_path.read_text()
        spec_content = yaml.dump(spec, sort_keys=True)
        checksum = _sha256(spec_content + template_content)

        existing_record = session.exec(
            select(SeedRecord).where(SeedRecord.seed_key == seed_key)
        ).first()
        if existing_record:
            if existing_record.checksum == checksum and existing_record.seed_version == version:
                # Still need to set operations_workgroup_id if this is the operations seed
                if seed_key == "default-operations" and not seed_org.operations_workgroup_id:
                    ops_wg = session.get(Workgroup, existing_record.entity_id)
                    if ops_wg:
                        seed_org.operations_workgroup_id = ops_wg.id
                        session.add(seed_org)
                continue
            logger.warning(
                "Seed %s content changed (version %s→%s) — skipping to preserve user modifications",
                seed_key,
                existing_record.seed_version,
                version,
            )
            continue

        try:
            session.begin_nested()
            _create_workgroup_from_template(
                session, system_user, seed_org, spec, template_content, version, checksum,
            )
        except Exception:
            logger.exception("Failed to seed workgroup %s — rolling back this workgroup only", seed_key)
            session.rollback()
            continue

        # After successfully creating the operations workgroup, link it to the org
        if seed_key == "default-operations":
            ops_record = session.exec(
                select(SeedRecord).where(SeedRecord.seed_key == "default-operations")
            ).first()
            if ops_record:
                seed_org.operations_workgroup_id = ops_record.entity_id
                session.add(seed_org)


def _create_workgroup_from_template(
    session: Session,
    system_user: User,
    seed_org: Organization,
    spec: dict,
    template_content: str,
    version: int,
    checksum: str,
) -> None:
    from teaparty_app.services.workgroup_templates import _normalize_storage_template

    template_data = yaml.safe_load(template_content) or {}
    template = _normalize_storage_template(template_data)
    if not template:
        logger.warning("Could not normalize template for seed %s", spec.get("seed_key"))
        return

    workgroup_name = spec.get("name") or template["name"]
    files = [{"id": new_id(), "path": f["path"], "content": f["content"]} for f in template["files"]]

    workgroup = Workgroup(
        name=workgroup_name,
        files=files,
        owner_id=system_user.id,
        organization_id=seed_org.id,
    )
    session.add(workgroup)
    session.flush()

    membership = Membership(
        workgroup_id=workgroup.id,
        user_id=system_user.id,
        role="owner",
    )
    session.add(membership)

    for agent_def in template["agents"]:
        agent = Agent(
            workgroup_id=workgroup.id,
            created_by_user_id=system_user.id,
            name=agent_def["name"],
            description=agent_def.get("description", ""),
            prompt=agent_def.get("prompt", ""),
            model=agent_def.get("model", "sonnet"),
            tools=agent_def.get("tools", []),
        )
        session.add(agent)

    session.flush()

    from teaparty_app.services.activity import ensure_activity_conversation

    ensure_activity_conversation(session, workgroup)

    session.add(SeedRecord(
        seed_key=spec["seed_key"],
        entity_type="workgroup",
        entity_id=workgroup.id,
        seed_version=version,
        checksum=checksum,
    ))
