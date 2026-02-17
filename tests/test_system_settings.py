import unittest

from fastapi import HTTPException

from teaparty_app.config import Settings
from teaparty_app.deps import require_system_admin
from teaparty_app.models import User
from teaparty_app.routers.system import _read_settings, EDITABLE_FIELDS
from teaparty_app.schemas import SystemSettingsRead, SystemSettingsUpdate


class RequireSystemAdminTests(unittest.TestCase):
    def test_allows_system_admin(self) -> None:
        user = User(id="u1", email="admin@example.com", name="Admin", is_system_admin=True)
        result = require_system_admin(user)
        self.assertEqual(result.id, "u1")

    def test_rejects_non_admin(self) -> None:
        user = User(id="u2", email="user@example.com", name="User", is_system_admin=False)
        with self.assertRaises(HTTPException) as ctx:
            require_system_admin(user)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.detail, "System admin access required")


class ReadSettingsTests(unittest.TestCase):
    def test_returns_all_fields(self) -> None:
        result = _read_settings()
        self.assertIsInstance(result, SystemSettingsRead)
        self.assertIsInstance(result.anthropic_api_key_set, bool)
        self.assertIsInstance(result.agent_chain_max, int)

    def test_api_key_is_masked(self) -> None:
        result = _read_settings()
        # Should be a boolean, not the actual key
        self.assertIn(result.anthropic_api_key_set, (True, False))
        self.assertFalse(hasattr(result, "anthropic_api_key"))


class UpdateSettingsTests(unittest.TestCase):
    def test_update_schema_validation_bounds(self) -> None:
        # agent_chain_max must be 1-50
        with self.assertRaises(Exception):
            SystemSettingsUpdate(agent_chain_max=0)
        with self.assertRaises(Exception):
            SystemSettingsUpdate(agent_chain_max=51)

        # agent_sdk_max_turns must be 1-50
        with self.assertRaises(Exception):
            SystemSettingsUpdate(agent_sdk_max_turns=0)

    def test_update_schema_accepts_valid_values(self) -> None:
        update = SystemSettingsUpdate(agent_chain_max=10, agent_sdk_max_turns=20)
        self.assertEqual(update.agent_chain_max, 10)
        self.assertEqual(update.agent_sdk_max_turns, 20)

    def test_update_schema_all_optional(self) -> None:
        update = SystemSettingsUpdate()
        dumped = update.model_dump(exclude_unset=True)
        self.assertEqual(dumped, {})

    def test_editable_fields_list(self) -> None:
        # All fields in SystemSettingsUpdate should be in EDITABLE_FIELDS
        update_fields = set(SystemSettingsUpdate.model_fields.keys())
        self.assertEqual(update_fields, set(EDITABLE_FIELDS))
