import unittest

from sqlmodel import SQLModel, Session, create_engine, select

from teaparty_app.models import (
    Organization,
    SeedRecord,
    User,
    Workgroup,
)
from teaparty_app.seeds.runner import (
    SYSTEM_USER_EMAIL,
    SYSTEM_USER_NAME,
    run_seeds,
    _ensure_system_user,
)


class EnsureSystemUserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(self.engine)

    def test_creates_system_user(self) -> None:
        with Session(self.engine) as session:
            user = _ensure_system_user(session)
            session.commit()
            session.refresh(user)
            user_id = user.id
            user_email = user.email
            user_name = user.name

        self.assertEqual(user_email, SYSTEM_USER_EMAIL)
        self.assertEqual(user_name, SYSTEM_USER_NAME)

        with Session(self.engine) as session:
            record = session.exec(
                select(SeedRecord).where(SeedRecord.seed_key == "system-user")
            ).first()
            self.assertIsNotNone(record)
            self.assertEqual(record.entity_type, "user")
            self.assertEqual(record.entity_id, user_id)

    def test_idempotent(self) -> None:
        with Session(self.engine) as session:
            user1 = _ensure_system_user(session)
            session.commit()
            session.refresh(user1)
            user1_id = user1.id

        with Session(self.engine) as session:
            user2 = _ensure_system_user(session)
            session.commit()
            session.refresh(user2)
            user2_id = user2.id

        self.assertEqual(user1_id, user2_id)

        with Session(self.engine) as session:
            records = session.exec(
                select(SeedRecord).where(SeedRecord.seed_key == "system-user")
            ).all()
            self.assertEqual(len(records), 1)

    def test_recovers_existing_user_without_seed_record(self) -> None:
        with Session(self.engine) as session:
            user = User(email=SYSTEM_USER_EMAIL, name="Already Exists")
            session.add(user)
            session.commit()
            session.refresh(user)
            existing_id = user.id

        with Session(self.engine) as session:
            result = _ensure_system_user(session)
            session.commit()
            session.refresh(result)
            result_id = result.id

        self.assertEqual(result_id, existing_id)

        with Session(self.engine) as session:
            record = session.exec(
                select(SeedRecord).where(SeedRecord.seed_key == "system-user")
            ).first()
            self.assertIsNotNone(record)
            self.assertEqual(record.entity_id, existing_id)


class RunSeedsIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(self.engine)

    def test_run_seeds_end_to_end(self) -> None:
        run_seeds(self.engine)

        with Session(self.engine) as session:
            user = session.exec(
                select(User).where(User.email == SYSTEM_USER_EMAIL)
            ).first()
            self.assertIsNotNone(user)

            # No auto-created workgroups or organizations
            workgroups = session.exec(select(Workgroup)).all()
            self.assertEqual(len(workgroups), 0)

            orgs = session.exec(select(Organization)).all()
            self.assertEqual(len(orgs), 0)

            records = session.exec(select(SeedRecord)).all()
            self.assertEqual(len(records), 1)  # system-user only

    def test_run_seeds_idempotent(self) -> None:
        run_seeds(self.engine)
        run_seeds(self.engine)

        with Session(self.engine) as session:
            users = session.exec(
                select(User).where(User.email == SYSTEM_USER_EMAIL)
            ).all()
            self.assertEqual(len(users), 1)
