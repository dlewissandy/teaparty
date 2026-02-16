import unittest

from sqlmodel import SQLModel, Session, create_engine, select

from teaparty_app.models import (
    Agent,
    Membership,
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
    _ensure_seed_organization,
    _seed_default_workgroups,
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


class SeedDefaultWorkgroupsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(self.engine)

    def _setup_seed_org(self, session: Session) -> tuple[User, Organization]:
        system_user = _ensure_system_user(session)
        seed_org = _ensure_seed_organization(session, system_user)
        return system_user, seed_org

    def test_seeds_all_default_workgroups(self) -> None:
        with Session(self.engine) as session:
            system_user, seed_org = self._setup_seed_org(session)
            _seed_default_workgroups(session, system_user, seed_org)
            session.commit()

        with Session(self.engine) as session:
            workgroups = session.exec(select(Workgroup)).all()
            names = {wg.name for wg in workgroups}
            self.assertIn("Coding", names)
            self.assertIn("Dialectic", names)
            self.assertIn("Roleplay", names)
            for wg in workgroups:
                self.assertIsNotNone(wg.organization_id)

    def test_creates_agents_for_each_workgroup(self) -> None:
        with Session(self.engine) as session:
            system_user, seed_org = self._setup_seed_org(session)
            _seed_default_workgroups(session, system_user, seed_org)
            session.commit()

        with Session(self.engine) as session:
            agents = session.exec(select(Agent)).all()
            agent_names = {a.name for a in agents}
            # Coding agents
            self.assertIn("Implementer", agent_names)
            self.assertIn("Reviewer", agent_names)
            # Dialectic agents
            self.assertIn("Proponent", agent_names)
            self.assertIn("Opponent", agent_names)
            self.assertIn("Synthesist", agent_names)
            self.assertIn("Neophyte", agent_names)
            # Roleplay agents
            self.assertIn("Scene Director", agent_names)
            self.assertIn("Character Coach", agent_names)

    def test_creates_seed_records(self) -> None:
        with Session(self.engine) as session:
            system_user, seed_org = self._setup_seed_org(session)
            _seed_default_workgroups(session, system_user, seed_org)
            session.commit()

        with Session(self.engine) as session:
            records = session.exec(select(SeedRecord)).all()
            keys = {r.seed_key for r in records}
            self.assertIn("system-user", keys)
            self.assertIn("seed-organization", keys)
            self.assertIn("default-coding", keys)
            self.assertIn("default-dialectic", keys)
            self.assertIn("default-roleplay", keys)

    def test_creates_owner_membership(self) -> None:
        with Session(self.engine) as session:
            system_user, seed_org = self._setup_seed_org(session)
            _seed_default_workgroups(session, system_user, seed_org)
            session.commit()
            uid = system_user.id

        with Session(self.engine) as session:
            memberships = session.exec(
                select(Membership).where(Membership.user_id == uid)
            ).all()
            self.assertEqual(len(memberships), 4)
            self.assertTrue(all(m.role == "owner" for m in memberships))

    def test_idempotent(self) -> None:
        with Session(self.engine) as session:
            system_user, seed_org = self._setup_seed_org(session)
            _seed_default_workgroups(session, system_user, seed_org)
            session.commit()

        with Session(self.engine) as session:
            wg_count_1 = len(session.exec(select(Workgroup)).all())

        with Session(self.engine) as session:
            system_user, seed_org = self._setup_seed_org(session)
            _seed_default_workgroups(session, system_user, seed_org)
            session.commit()

        with Session(self.engine) as session:
            wg_count_2 = len(session.exec(select(Workgroup)).all())
            self.assertEqual(wg_count_1, wg_count_2)


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

            workgroups = session.exec(select(Workgroup)).all()
            self.assertEqual(len(workgroups), 4)
            for wg in workgroups:
                self.assertIsNotNone(wg.organization_id)

            orgs = session.exec(select(Organization)).all()
            self.assertEqual(len(orgs), 1)

            records = session.exec(select(SeedRecord)).all()
            self.assertEqual(len(records), 6)  # system-user + seed-organization + 4 workgroups

    def test_run_seeds_idempotent(self) -> None:
        run_seeds(self.engine)
        run_seeds(self.engine)

        with Session(self.engine) as session:
            workgroups = session.exec(select(Workgroup)).all()
            self.assertEqual(len(workgroups), 4)

            orgs = session.exec(select(Organization)).all()
            self.assertEqual(len(orgs), 1)

            users = session.exec(
                select(User).where(User.email == SYSTEM_USER_EMAIL)
            ).all()
            self.assertEqual(len(users), 1)
