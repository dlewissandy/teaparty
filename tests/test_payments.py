import unittest

from sqlmodel import SQLModel, Session, create_engine

from teaparty_app.models import (
    Conversation,
    Engagement,
    OrgBalance,
    Organization,
    PaymentTransaction,
    User,
    Workgroup,
)
from teaparty_app.services.payments import (
    InsufficientBalanceError,
    add_credits,
    escrow_for_engagement,
    get_or_create_balance,
    refund_escrow,
    release_escrow,
)


def _make_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def _make_user(session: Session, user_id: str) -> User:
    user = User(id=user_id, email=f"{user_id}@example.com", name=user_id)
    session.add(user)
    session.flush()
    return user


def _make_org(session: Session, user: User, org_id: str, name: str) -> Organization:
    org = Organization(id=org_id, name=name, owner_id=user.id)
    session.add(org)
    session.flush()
    return org


def _make_workgroup(
    session: Session,
    user: User,
    org: Organization,
    wg_id: str,
    name: str,
) -> Workgroup:
    wg = Workgroup(id=wg_id, name=name, owner_id=user.id, organization_id=org.id, files=[])
    session.add(wg)
    session.flush()
    return wg


def _make_engagement(
    session: Session,
    source_wg_id: str,
    target_wg_id: str,
    user_id: str,
    price: float | None = None,
) -> Engagement:
    eng = Engagement(
        source_workgroup_id=source_wg_id,
        target_workgroup_id=target_wg_id,
        proposed_by_user_id=user_id,
        status="in_progress",
        title="Test Engagement",
        scope="Test scope",
        requirements="Do the thing",
        agreed_price_credits=price,
    )
    session.add(eng)
    session.flush()

    src_conv = Conversation(
        workgroup_id=source_wg_id,
        created_by_user_id=user_id,
        kind="engagement",
        topic=f"engagement:{eng.id}",
        name="Test Engagement",
    )
    tgt_conv = Conversation(
        workgroup_id=target_wg_id,
        created_by_user_id=user_id,
        kind="engagement",
        topic=f"engagement:{eng.id}",
        name="Test Engagement",
    )
    session.add(src_conv)
    session.add(tgt_conv)
    session.flush()

    eng.source_conversation_id = src_conv.id
    eng.target_conversation_id = tgt_conv.id
    session.add(eng)
    session.flush()
    return eng


class GetOrCreateBalanceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _make_engine()

    def test_creates_new_balance_when_none_exists(self) -> None:
        with Session(self.engine) as session:
            user = _make_user(session, "u-1")
            org = _make_org(session, user, "org-1", "Acme")
            session.commit()

        with Session(self.engine) as session:
            balance = get_or_create_balance(session, "org-1")
            session.commit()

            self.assertIsNotNone(balance)
            self.assertEqual(balance.organization_id, "org-1")
            self.assertEqual(balance.balance_credits, 0.0)

    def test_returns_existing_balance(self) -> None:
        with Session(self.engine) as session:
            user = _make_user(session, "u-1")
            org = _make_org(session, user, "org-1", "Acme")
            existing = OrgBalance(organization_id="org-1", balance_credits=50.0)
            session.add(existing)
            session.commit()
            balance_id = existing.id

        with Session(self.engine) as session:
            balance = get_or_create_balance(session, "org-1")
            session.commit()

            self.assertEqual(balance.id, balance_id)
            self.assertEqual(balance.balance_credits, 50.0)

    def test_does_not_create_duplicate_balance(self) -> None:
        with Session(self.engine) as session:
            user = _make_user(session, "u-1")
            org = _make_org(session, user, "org-1", "Acme")
            session.commit()

        with Session(self.engine) as session:
            get_or_create_balance(session, "org-1")
            get_or_create_balance(session, "org-1")
            session.commit()

        with Session(self.engine) as session:
            from sqlmodel import select
            rows = session.exec(
                select(OrgBalance).where(OrgBalance.organization_id == "org-1")
            ).all()
            self.assertEqual(len(rows), 1)


class AddCreditsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _make_engine()

    def test_increases_balance_and_creates_transaction(self) -> None:
        with Session(self.engine) as session:
            user = _make_user(session, "u-1")
            org = _make_org(session, user, "org-1", "Acme")
            session.commit()

        with Session(self.engine) as session:
            txn = add_credits(session, "org-1", 100.0, "Initial top-up")
            session.commit()

            self.assertIsNotNone(txn)
            self.assertEqual(txn.organization_id, "org-1")
            self.assertEqual(txn.transaction_type, "credit")
            self.assertEqual(txn.amount_credits, 100.0)
            self.assertEqual(txn.balance_after_credits, 100.0)
            self.assertEqual(txn.description, "Initial top-up")

        with Session(self.engine) as session:
            balance = get_or_create_balance(session, "org-1")
            self.assertEqual(balance.balance_credits, 100.0)

    def test_add_credits_accumulates_across_calls(self) -> None:
        with Session(self.engine) as session:
            user = _make_user(session, "u-1")
            org = _make_org(session, user, "org-1", "Acme")
            session.commit()

        with Session(self.engine) as session:
            add_credits(session, "org-1", 50.0)
            add_credits(session, "org-1", 75.0)
            session.commit()

        with Session(self.engine) as session:
            balance = get_or_create_balance(session, "org-1")
            self.assertEqual(balance.balance_credits, 125.0)

    def test_add_credits_uses_default_description(self) -> None:
        with Session(self.engine) as session:
            user = _make_user(session, "u-1")
            org = _make_org(session, user, "org-1", "Acme")
            session.commit()

        with Session(self.engine) as session:
            txn = add_credits(session, "org-1", 10.0)
            session.commit()

            self.assertEqual(txn.description, "Credits added")

    def test_add_credits_records_correct_balance_after(self) -> None:
        with Session(self.engine) as session:
            user = _make_user(session, "u-1")
            org = _make_org(session, user, "org-1", "Acme")
            existing = OrgBalance(organization_id="org-1", balance_credits=200.0)
            session.add(existing)
            session.commit()

        with Session(self.engine) as session:
            txn = add_credits(session, "org-1", 50.0)
            session.commit()

            self.assertEqual(txn.balance_after_credits, 250.0)


class EscrowForEngagementTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _make_engine()

        with Session(self.engine) as session:
            u_src = _make_user(session, "u-src")
            u_tgt = _make_user(session, "u-tgt")
            org_src = _make_org(session, u_src, "org-src", "Source Org")
            org_tgt = _make_org(session, u_tgt, "org-tgt", "Target Org")
            _make_workgroup(session, u_src, org_src, "wg-src", "Source WG")
            _make_workgroup(session, u_tgt, org_tgt, "wg-tgt", "Target WG")
            session.commit()

    def _fund_source_org(self, amount: float) -> None:
        with Session(self.engine) as session:
            add_credits(session, "org-src", amount, "Test funding")
            session.commit()

    def test_escrow_deducts_from_source_and_sets_status(self) -> None:
        self._fund_source_org(500.0)

        with Session(self.engine) as session:
            eng = _make_engagement(session, "wg-src", "wg-tgt", "u-src", price=100.0)
            session.commit()
            eng_id = eng.id

        with Session(self.engine) as session:
            eng = session.get(Engagement, eng_id)
            txn = escrow_for_engagement(session, eng)
            session.commit()

            self.assertIsNotNone(txn)
            self.assertEqual(txn.transaction_type, "escrow")
            self.assertEqual(txn.amount_credits, -100.0)
            self.assertEqual(txn.organization_id, "org-src")
            self.assertEqual(txn.counterparty_org_id, "org-tgt")
            self.assertEqual(txn.engagement_id, eng_id)

        with Session(self.engine) as session:
            eng = session.get(Engagement, eng_id)
            self.assertEqual(eng.payment_status, "escrowed")

            balance = get_or_create_balance(session, "org-src")
            self.assertEqual(balance.balance_credits, 400.0)

    def test_escrow_returns_none_for_free_engagement(self) -> None:
        with Session(self.engine) as session:
            eng = _make_engagement(session, "wg-src", "wg-tgt", "u-src", price=None)
            session.commit()
            eng_id = eng.id

        with Session(self.engine) as session:
            eng = session.get(Engagement, eng_id)
            result = escrow_for_engagement(session, eng)
            session.commit()

            self.assertIsNone(result)

        with Session(self.engine) as session:
            eng = session.get(Engagement, eng_id)
            self.assertEqual(eng.payment_status, "none")

    def test_escrow_returns_none_for_zero_price(self) -> None:
        with Session(self.engine) as session:
            eng = _make_engagement(session, "wg-src", "wg-tgt", "u-src", price=0.0)
            session.commit()
            eng_id = eng.id

        with Session(self.engine) as session:
            eng = session.get(Engagement, eng_id)
            result = escrow_for_engagement(session, eng)
            session.commit()

            self.assertIsNone(result)

    def test_escrow_raises_insufficient_balance_error(self) -> None:
        self._fund_source_org(50.0)

        with Session(self.engine) as session:
            eng = _make_engagement(session, "wg-src", "wg-tgt", "u-src", price=100.0)
            session.commit()
            eng_id = eng.id

        with Session(self.engine) as session:
            eng = session.get(Engagement, eng_id)
            with self.assertRaises(InsufficientBalanceError) as ctx:
                escrow_for_engagement(session, eng)

            self.assertEqual(ctx.exception.available, 50.0)
            self.assertEqual(ctx.exception.required, 100.0)

    def test_escrow_raises_when_balance_is_zero(self) -> None:
        with Session(self.engine) as session:
            eng = _make_engagement(session, "wg-src", "wg-tgt", "u-src", price=10.0)
            session.commit()
            eng_id = eng.id

        with Session(self.engine) as session:
            eng = session.get(Engagement, eng_id)
            with self.assertRaises(InsufficientBalanceError):
                escrow_for_engagement(session, eng)

    def test_escrow_balance_after_reflects_remaining(self) -> None:
        self._fund_source_org(300.0)

        with Session(self.engine) as session:
            eng = _make_engagement(session, "wg-src", "wg-tgt", "u-src", price=120.0)
            session.commit()
            eng_id = eng.id

        with Session(self.engine) as session:
            eng = session.get(Engagement, eng_id)
            txn = escrow_for_engagement(session, eng)
            session.commit()

            self.assertEqual(txn.balance_after_credits, 180.0)


class ReleaseEscrowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _make_engine()

        with Session(self.engine) as session:
            u_src = _make_user(session, "u-src")
            u_tgt = _make_user(session, "u-tgt")
            org_src = _make_org(session, u_src, "org-src", "Source Org")
            org_tgt = _make_org(session, u_tgt, "org-tgt", "Target Org")
            _make_workgroup(session, u_src, org_src, "wg-src", "Source WG")
            _make_workgroup(session, u_tgt, org_tgt, "wg-tgt", "Target WG")
            session.commit()

    def _setup_escrowed_engagement(self, price: float = 200.0) -> str:
        with Session(self.engine) as session:
            add_credits(session, "org-src", price + 100.0, "Fund source")
            session.commit()

        with Session(self.engine) as session:
            eng = _make_engagement(session, "wg-src", "wg-tgt", "u-src", price=price)
            session.commit()
            eng_id = eng.id

        with Session(self.engine) as session:
            eng = session.get(Engagement, eng_id)
            escrow_for_engagement(session, eng)
            session.commit()

        return eng_id

    def test_release_credits_target_org_and_sets_paid(self) -> None:
        eng_id = self._setup_escrowed_engagement(price=200.0)

        with Session(self.engine) as session:
            eng = session.get(Engagement, eng_id)
            txn = release_escrow(session, eng)
            session.commit()

            self.assertIsNotNone(txn)
            self.assertEqual(txn.transaction_type, "release")
            self.assertEqual(txn.amount_credits, 200.0)
            self.assertEqual(txn.organization_id, "org-tgt")
            self.assertEqual(txn.counterparty_org_id, "org-src")
            self.assertEqual(txn.engagement_id, eng_id)

        with Session(self.engine) as session:
            eng = session.get(Engagement, eng_id)
            self.assertEqual(eng.payment_status, "paid")

            target_balance = get_or_create_balance(session, "org-tgt")
            self.assertEqual(target_balance.balance_credits, 200.0)

    def test_release_returns_none_if_not_escrowed(self) -> None:
        with Session(self.engine) as session:
            eng = _make_engagement(session, "wg-src", "wg-tgt", "u-src", price=100.0)
            session.commit()
            eng_id = eng.id

        with Session(self.engine) as session:
            eng = session.get(Engagement, eng_id)
            # payment_status is "none" by default, not "escrowed"
            result = release_escrow(session, eng)
            session.commit()

            self.assertIsNone(result)

    def test_release_returns_none_if_already_paid(self) -> None:
        eng_id = self._setup_escrowed_engagement(price=100.0)

        with Session(self.engine) as session:
            eng = session.get(Engagement, eng_id)
            release_escrow(session, eng)
            session.commit()

        with Session(self.engine) as session:
            eng = session.get(Engagement, eng_id)
            self.assertEqual(eng.payment_status, "paid")
            result = release_escrow(session, eng)
            session.commit()

            self.assertIsNone(result)

    def test_release_does_not_deduct_from_source(self) -> None:
        eng_id = self._setup_escrowed_engagement(price=150.0)

        with Session(self.engine) as session:
            source_balance_before = get_or_create_balance(session, "org-src")
            balance_before = source_balance_before.balance_credits

        with Session(self.engine) as session:
            eng = session.get(Engagement, eng_id)
            release_escrow(session, eng)
            session.commit()

        with Session(self.engine) as session:
            source_balance_after = get_or_create_balance(session, "org-src")
            # Source balance should not change during release; funds were already removed at escrow time
            self.assertEqual(source_balance_after.balance_credits, balance_before)

    def test_release_records_correct_balance_after_for_target(self) -> None:
        eng_id = self._setup_escrowed_engagement(price=75.0)

        with Session(self.engine) as session:
            add_credits(session, "org-tgt", 25.0, "Existing target credits")
            session.commit()

        with Session(self.engine) as session:
            eng = session.get(Engagement, eng_id)
            txn = release_escrow(session, eng)
            session.commit()

            self.assertEqual(txn.balance_after_credits, 100.0)


class RefundEscrowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _make_engine()

        with Session(self.engine) as session:
            u_src = _make_user(session, "u-src")
            u_tgt = _make_user(session, "u-tgt")
            org_src = _make_org(session, u_src, "org-src", "Source Org")
            org_tgt = _make_org(session, u_tgt, "org-tgt", "Target Org")
            _make_workgroup(session, u_src, org_src, "wg-src", "Source WG")
            _make_workgroup(session, u_tgt, org_tgt, "wg-tgt", "Target WG")
            session.commit()

    def _setup_escrowed_engagement(self, price: float = 200.0) -> str:
        with Session(self.engine) as session:
            add_credits(session, "org-src", price + 100.0, "Fund source")
            session.commit()

        with Session(self.engine) as session:
            eng = _make_engagement(session, "wg-src", "wg-tgt", "u-src", price=price)
            session.commit()
            eng_id = eng.id

        with Session(self.engine) as session:
            eng = session.get(Engagement, eng_id)
            escrow_for_engagement(session, eng)
            session.commit()

        return eng_id

    def test_refund_returns_credits_to_source_and_sets_refunded(self) -> None:
        eng_id = self._setup_escrowed_engagement(price=200.0)

        with Session(self.engine) as session:
            source_balance_after_escrow = get_or_create_balance(session, "org-src")
            balance_after_escrow = source_balance_after_escrow.balance_credits

        with Session(self.engine) as session:
            eng = session.get(Engagement, eng_id)
            txn = refund_escrow(session, eng)
            session.commit()

            self.assertIsNotNone(txn)
            self.assertEqual(txn.transaction_type, "refund")
            self.assertEqual(txn.amount_credits, 200.0)
            self.assertEqual(txn.organization_id, "org-src")
            self.assertEqual(txn.counterparty_org_id, "org-tgt")
            self.assertEqual(txn.engagement_id, eng_id)

        with Session(self.engine) as session:
            eng = session.get(Engagement, eng_id)
            self.assertEqual(eng.payment_status, "refunded")

            source_balance = get_or_create_balance(session, "org-src")
            self.assertEqual(source_balance.balance_credits, balance_after_escrow + 200.0)

    def test_refund_returns_none_if_not_escrowed(self) -> None:
        with Session(self.engine) as session:
            eng = _make_engagement(session, "wg-src", "wg-tgt", "u-src", price=100.0)
            session.commit()
            eng_id = eng.id

        with Session(self.engine) as session:
            eng = session.get(Engagement, eng_id)
            # payment_status defaults to "none"
            result = refund_escrow(session, eng)
            session.commit()

            self.assertIsNone(result)

    def test_refund_returns_none_if_already_refunded(self) -> None:
        eng_id = self._setup_escrowed_engagement(price=100.0)

        with Session(self.engine) as session:
            eng = session.get(Engagement, eng_id)
            refund_escrow(session, eng)
            session.commit()

        with Session(self.engine) as session:
            eng = session.get(Engagement, eng_id)
            self.assertEqual(eng.payment_status, "refunded")
            result = refund_escrow(session, eng)
            session.commit()

            self.assertIsNone(result)

    def test_refund_does_not_credit_target_org(self) -> None:
        eng_id = self._setup_escrowed_engagement(price=100.0)

        with Session(self.engine) as session:
            eng = session.get(Engagement, eng_id)
            refund_escrow(session, eng)
            session.commit()

        with Session(self.engine) as session:
            target_balance = get_or_create_balance(session, "org-tgt")
            self.assertEqual(target_balance.balance_credits, 0.0)

    def test_refund_restores_full_original_balance(self) -> None:
        price = 150.0
        starting_funds = price + 100.0  # 250.0 total

        with Session(self.engine) as session:
            add_credits(session, "org-src", starting_funds, "Seed")
            session.commit()

        with Session(self.engine) as session:
            eng = _make_engagement(session, "wg-src", "wg-tgt", "u-src", price=price)
            session.commit()
            eng_id = eng.id

        with Session(self.engine) as session:
            eng = session.get(Engagement, eng_id)
            escrow_for_engagement(session, eng)
            session.commit()

        with Session(self.engine) as session:
            eng = session.get(Engagement, eng_id)
            refund_escrow(session, eng)
            session.commit()

        with Session(self.engine) as session:
            source_balance = get_or_create_balance(session, "org-src")
            self.assertEqual(source_balance.balance_credits, starting_funds)

    def test_refund_records_balance_after_credits(self) -> None:
        eng_id = self._setup_escrowed_engagement(price=80.0)

        with Session(self.engine) as session:
            source_balance_mid = get_or_create_balance(session, "org-src")
            balance_mid = source_balance_mid.balance_credits

        with Session(self.engine) as session:
            eng = session.get(Engagement, eng_id)
            txn = refund_escrow(session, eng)
            session.commit()

            self.assertEqual(txn.balance_after_credits, balance_mid + 80.0)


class InsufficientBalanceErrorTest(unittest.TestCase):
    def test_error_stores_available_and_required(self) -> None:
        err = InsufficientBalanceError(available=10.0, required=50.0)
        self.assertEqual(err.available, 10.0)
        self.assertEqual(err.required, 50.0)

    def test_error_message_is_descriptive(self) -> None:
        err = InsufficientBalanceError(available=10.0, required=50.0)
        self.assertIn("10.0", str(err))
        self.assertIn("50.0", str(err))

    def test_error_is_exception_subclass(self) -> None:
        err = InsufficientBalanceError(available=0.0, required=1.0)
        self.assertIsInstance(err, Exception)


if __name__ == "__main__":
    unittest.main()
