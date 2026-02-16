import unittest

from fastapi import HTTPException

from teaparty_app.routers.workgroups import (
    _reconcile_administration_template_files,
    _resolve_template_for_create,
    _resolve_workgroup_creation_agents,
    _resolve_workgroup_creation_files,
)
from teaparty_app.schemas import WorkgroupCreateRequest, WorkgroupTemplateRead
from teaparty_app.services.workgroup_templates import (
    get_workgroup_template,
    list_workgroup_templates,
    template_storage_files,
    templates_from_storage_files,
)


class WorkgroupTemplateTests(unittest.TestCase):
    @staticmethod
    def _template_lookup() -> dict[str, WorkgroupTemplateRead]:
        rows = [WorkgroupTemplateRead.model_validate(item) for item in list_workgroup_templates()]
        return {item.key: item for item in rows}

    def test_list_templates_contains_expected_keys(self) -> None:
        templates = list_workgroup_templates()
        keys = {template["key"] for template in templates}
        self.assertEqual(keys, {"coding", "dialectic", "operations", "roleplay"})
        self.assertTrue(all(template["agents"] for template in templates))

    def test_get_template_returns_copy(self) -> None:
        original = get_workgroup_template("coding")
        self.assertIsNotNone(original)
        if original is None:
            self.fail("Expected coding template")
        original["files"][0]["path"] = "modified.md"

        fetched_again = get_workgroup_template("coding")
        self.assertIsNotNone(fetched_again)
        if fetched_again is None:
            self.fail("Expected coding template on second fetch")
        self.assertNotEqual(fetched_again["files"][0]["path"], "modified.md")

    def test_get_template_returns_none_for_unknown_key(self) -> None:
        self.assertIsNone(get_workgroup_template("unknown-template"))

    def test_resolve_creation_files_uses_template_when_files_omitted(self) -> None:
        payload = WorkgroupCreateRequest(name="Dialectic Team", template_key="dialectic", organization_id="org-1")
        template = _resolve_template_for_create(payload, self._template_lookup())
        files = _resolve_workgroup_creation_files(payload, template)
        self.assertGreater(len(files), 0)
        self.assertTrue(any(item["path"] == "topic.md" for item in files))

    def test_resolve_creation_agents_uses_template_when_agents_omitted(self) -> None:
        payload = WorkgroupCreateRequest(name="Dialectic Team", template_key="dialectic", organization_id="org-1")
        template = _resolve_template_for_create(payload, self._template_lookup())
        agents = _resolve_workgroup_creation_agents(payload, template)
        self.assertGreater(len(agents), 0)
        self.assertTrue(any(item.name == "Synthesist" for item in agents))

    def test_resolve_creation_files_prefers_explicit_files(self) -> None:
        payload = WorkgroupCreateRequest(
            name="Research",
            template_key="dialectic",
            files=[{"path": "notes/custom.md", "content": "custom"}],
            organization_id="org-1",
        )
        template = _resolve_template_for_create(payload, self._template_lookup())
        files = _resolve_workgroup_creation_files(payload, template)
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0]["path"], "notes/custom.md")

    def test_resolve_creation_agents_prefers_explicit_agents(self) -> None:
        payload = WorkgroupCreateRequest(
            name="Research",
            template_key="dialectic",
            agents=[
                {
                    "name": "Custom Analyst",
                    "role": "Custom role",
                    "tool_names": ["summarize_topic"],
                }
            ],
            organization_id="org-1",
        )
        template = _resolve_template_for_create(payload, self._template_lookup())
        agents = _resolve_workgroup_creation_agents(payload, template)
        self.assertEqual(len(agents), 1)
        self.assertEqual(agents[0].name, "Custom Analyst")

    def test_resolve_creation_files_allows_explicit_empty_override(self) -> None:
        payload = WorkgroupCreateRequest(name="Research", template_key="dialectic", files=[], organization_id="org-1")
        template = _resolve_template_for_create(payload, self._template_lookup())
        files = _resolve_workgroup_creation_files(payload, template)
        self.assertEqual(files, [])

    def test_resolve_creation_agents_allows_explicit_empty_override(self) -> None:
        payload = WorkgroupCreateRequest(name="Research", template_key="dialectic", agents=[], organization_id="org-1")
        template = _resolve_template_for_create(payload, self._template_lookup())
        agents = _resolve_workgroup_creation_agents(payload, template)
        self.assertEqual(agents, [])

    def test_resolve_creation_files_raises_for_unknown_template(self) -> None:
        payload = WorkgroupCreateRequest(name="Project", template_key="missing-key", organization_id="org-1")
        with self.assertRaises(HTTPException) as ctx:
            _resolve_template_for_create(payload, self._template_lookup())
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("Unknown workgroup template", str(ctx.exception.detail))

    def test_storage_files_round_trip(self) -> None:
        storage_files = template_storage_files()
        parsed = templates_from_storage_files(storage_files)
        self.assertEqual(
            {item["key"] for item in parsed},
            {"coding", "dialectic", "operations", "roleplay"},
        )

    def test_storage_files_include_required_structure(self) -> None:
        storage_files = template_storage_files()
        paths = {item["path"] for item in storage_files}
        self.assertIn(".templates/organizations/default/organization.json", paths)
        for template_key in ("coding", "dialectic", "operations", "roleplay"):
            config_path = f".templates/organizations/default/workgroups/{template_key}/workgroup.json"
            self.assertIn(config_path, paths)
            self.assertTrue(any(path.startswith(f".templates/organizations/default/workgroups/{template_key}/agents/") for path in paths))
            self.assertTrue(any(path.startswith(f".templates/organizations/default/workgroups/{template_key}/files/") for path in paths))

    def test_administration_template_reconcile_prunes_legacy_entries(self) -> None:
        existing_files = [
            {"id": "a", "path": ".templates/workgroups/coding/workgroup.json", "content": "{}"},
            {"id": "b", "path": ".templates/workgroups/coding/config.json", "content": "{}"},
            {"id": "c", "path": "templates/coding.json", "content": "{}"},
            {"id": "d", "path": "notes.txt", "content": "keep"},
        ]

        reconciled, changed = _reconcile_administration_template_files(existing_files)
        paths = {item["path"] for item in reconciled}

        self.assertTrue(changed)
        self.assertIn("notes.txt", paths)
        self.assertFalse(any(path.startswith("templates/") for path in paths))
        self.assertFalse(any(path.endswith("/config.json") for path in paths))
        self.assertIn(".templates/organizations/default/organization.json", paths)
        for template_key in ("coding", "dialectic", "operations", "roleplay"):
            self.assertIn(f".templates/organizations/default/workgroups/{template_key}/workgroup.json", paths)
