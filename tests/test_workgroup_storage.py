import json
import unittest

from teaparty_app.services.workgroup_templates import (
    WORKGROUP_STORAGE_ROOT,
    _is_workgroup_storage_path,
    workgroup_storage_files,
)


class IsWorkgroupStoragePathTests(unittest.TestCase):
    def test_matches_workgroups_readme(self) -> None:
        self.assertTrue(_is_workgroup_storage_path("workgroups/README.md"))

    def test_matches_workgroup_json(self) -> None:
        self.assertTrue(_is_workgroup_storage_path("workgroups/abc-123/workgroup.json"))

    def test_matches_agent_json(self) -> None:
        self.assertTrue(_is_workgroup_storage_path("workgroups/abc-123/agents/implementer.json"))

    def test_rejects_template_path(self) -> None:
        self.assertFalse(_is_workgroup_storage_path(".templates/workgroups/coding/workgroup.json"))

    def test_rejects_unrelated_path(self) -> None:
        self.assertFalse(_is_workgroup_storage_path("notes.txt"))

    def test_handles_backslash_paths(self) -> None:
        self.assertTrue(_is_workgroup_storage_path("workgroups\\abc-123\\workgroup.json"))

    def test_handles_leading_slash(self) -> None:
        self.assertTrue(_is_workgroup_storage_path("/workgroups/abc-123/workgroup.json"))


class WorkgroupStorageFilesTests(unittest.TestCase):
    def test_empty_workgroups(self) -> None:
        files = workgroup_storage_files([], {})
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0]["path"], f"{WORKGROUP_STORAGE_ROOT}/README.md")

    def test_single_workgroup_no_agents(self) -> None:
        workgroups = [
            {"id": "wg-1", "name": "My Project", "owner_id": "user-1", "created_at": "2026-01-01T00:00:00Z"},
        ]
        files = workgroup_storage_files(workgroups, {})
        paths = {f["path"] for f in files}

        self.assertIn(f"{WORKGROUP_STORAGE_ROOT}/README.md", paths)
        self.assertIn(f"{WORKGROUP_STORAGE_ROOT}/wg-1/workgroup.json", paths)
        self.assertEqual(len(files), 2)  # README + 1 workgroup.json

    def test_single_workgroup_with_agents(self) -> None:
        workgroups = [
            {"id": "wg-1", "name": "My Project", "owner_id": "user-1", "created_at": "2026-01-01T00:00:00Z"},
        ]
        agents_by_wg = {
            "wg-1": [
                {
                    "id": "agent-1",
                    "name": "Implementer",
                    "description": "Builds things",
                    "role": "Builder",
                    "personality": "Practical",
                    "backstory": "",
                    "model": "gpt-5-nano",
                    "temperature": 0.4,
                    "verbosity": 0.5,
                    "tool_names": ["summarize_topic"],
                    "response_threshold": 0.5,
                    "follow_up_minutes": 45,
                },
            ],
        }
        files = workgroup_storage_files(workgroups, agents_by_wg)
        paths = {f["path"] for f in files}

        self.assertIn(f"{WORKGROUP_STORAGE_ROOT}/wg-1/workgroup.json", paths)
        self.assertIn(f"{WORKGROUP_STORAGE_ROOT}/wg-1/agents/implementer.json", paths)
        self.assertEqual(len(files), 3)  # README + workgroup.json + agent.json

    def test_multiple_workgroups(self) -> None:
        workgroups = [
            {"id": "wg-1", "name": "Project A", "owner_id": "user-1", "created_at": "2026-01-01T00:00:00Z"},
            {"id": "wg-2", "name": "Project B", "owner_id": "user-2", "created_at": "2026-01-02T00:00:00Z"},
        ]
        agents_by_wg = {
            "wg-1": [
                {
                    "id": "a1", "name": "Coder", "description": "", "role": "", "personality": "",
                    "backstory": "", "model": "gpt-5-nano", "temperature": 0.7, "verbosity": 0.5,
                    "tool_names": [], "response_threshold": 0.55, "follow_up_minutes": 60,
                },
            ],
            "wg-2": [
                {
                    "id": "a2", "name": "Writer", "description": "", "role": "", "personality": "",
                    "backstory": "", "model": "gpt-5-nano", "temperature": 0.7, "verbosity": 0.5,
                    "tool_names": [], "response_threshold": 0.55, "follow_up_minutes": 60,
                },
            ],
        }
        files = workgroup_storage_files(workgroups, agents_by_wg)
        paths = {f["path"] for f in files}

        self.assertIn(f"{WORKGROUP_STORAGE_ROOT}/wg-1/workgroup.json", paths)
        self.assertIn(f"{WORKGROUP_STORAGE_ROOT}/wg-1/agents/coder.json", paths)
        self.assertIn(f"{WORKGROUP_STORAGE_ROOT}/wg-2/workgroup.json", paths)
        self.assertIn(f"{WORKGROUP_STORAGE_ROOT}/wg-2/agents/writer.json", paths)
        # README + 2 workgroup.json + 2 agents
        self.assertEqual(len(files), 5)

    def test_agent_slug_deduplication(self) -> None:
        workgroups = [
            {"id": "wg-1", "name": "Test", "owner_id": "u1", "created_at": "2026-01-01T00:00:00Z"},
        ]
        agents_by_wg = {
            "wg-1": [
                {
                    "id": "a1", "name": "Reviewer", "description": "First", "role": "", "personality": "",
                    "backstory": "", "model": "gpt-5-nano", "temperature": 0.7, "verbosity": 0.5,
                    "tool_names": [], "response_threshold": 0.55, "follow_up_minutes": 60,
                },
                {
                    "id": "a2", "name": "Reviewer", "description": "Second", "role": "", "personality": "",
                    "backstory": "", "model": "gpt-5-nano", "temperature": 0.7, "verbosity": 0.5,
                    "tool_names": [], "response_threshold": 0.55, "follow_up_minutes": 60,
                },
            ],
        }
        files = workgroup_storage_files(workgroups, agents_by_wg)
        paths = {f["path"] for f in files}

        self.assertIn(f"{WORKGROUP_STORAGE_ROOT}/wg-1/agents/reviewer.json", paths)
        self.assertIn(f"{WORKGROUP_STORAGE_ROOT}/wg-1/agents/reviewer_2.json", paths)

    def test_workgroup_json_contains_agent_refs(self) -> None:
        workgroups = [
            {
                "id": "wg-1", "name": "My Project", "owner_id": "user-1",
                "is_discoverable": True, "service_description": "Design help",
                "created_at": "2026-01-01T00:00:00Z",
            },
        ]
        agents_by_wg = {
            "wg-1": [
                {
                    "id": "agent-789", "name": "Implementer", "description": "Builds", "role": "Builder",
                    "personality": "Practical", "backstory": "", "model": "gpt-5-nano", "temperature": 0.4,
                    "verbosity": 0.5, "tool_names": [], "response_threshold": 0.5, "follow_up_minutes": 45,
                },
            ],
        }
        files = workgroup_storage_files(workgroups, agents_by_wg)
        wg_file = next(f for f in files if f["path"].endswith("workgroup.json"))
        payload = json.loads(wg_file["content"])

        self.assertEqual(payload["id"], "wg-1")
        self.assertEqual(payload["name"], "My Project")
        self.assertTrue(payload["is_discoverable"])
        self.assertEqual(payload["service_description"], "Design help")
        self.assertEqual(payload["members"], [])
        self.assertEqual(len(payload["agents"]), 1)
        self.assertEqual(payload["agents"][0]["id"], "agent-789")
        self.assertEqual(payload["agents"][0]["name"], "Implementer")
        self.assertEqual(payload["agents"][0]["role"], "Builder")

    def test_workgroup_json_contains_members(self) -> None:
        workgroups = [
            {
                "id": "wg-1", "name": "Team", "owner_id": "user-1",
                "is_discoverable": False, "service_description": "",
                "created_at": "2026-01-01T00:00:00Z",
            },
        ]
        agents_by_wg: dict[str, list[dict]] = {}
        members_by_wg = {
            "wg-1": [
                {"user_id": "user-1", "role": "owner"},
                {"user_id": "user-2", "role": "member"},
            ],
        }
        files = workgroup_storage_files(workgroups, agents_by_wg, members_by_wg)
        wg_file = next(f for f in files if f["path"].endswith("workgroup.json"))
        payload = json.loads(wg_file["content"])

        self.assertEqual(len(payload["members"]), 2)
        self.assertEqual(payload["members"][0]["user_id"], "user-1")
        self.assertEqual(payload["members"][0]["role"], "owner")
        self.assertEqual(payload["members"][1]["user_id"], "user-2")
        self.assertEqual(payload["members"][1]["role"], "member")

    def test_agent_json_excludes_runtime_state(self) -> None:
        workgroups = [
            {"id": "wg-1", "name": "Test", "owner_id": "u1", "created_at": "2026-01-01T00:00:00Z"},
        ]
        agents_by_wg = {
            "wg-1": [
                {
                    "id": "a1", "name": "Bot", "description": "Helper", "role": "Assistant",
                    "personality": "Friendly", "backstory": "None", "model": "gpt-5-nano",
                    "temperature": 0.7, "verbosity": 0.5, "tool_names": ["summarize_topic"],
                    "response_threshold": 0.55, "follow_up_minutes": 60,
                },
            ],
        }
        files = workgroup_storage_files(workgroups, agents_by_wg)
        agent_file = next(f for f in files if "agents/" in f["path"])
        payload = json.loads(agent_file["content"])

        self.assertEqual(payload["id"], "a1")
        self.assertEqual(payload["name"], "Bot")
        self.assertEqual(payload["tool_names"], ["summarize_topic"])
        self.assertNotIn("learning_state", payload)
        self.assertNotIn("sentiment_state", payload)
        self.assertNotIn("learned_preferences", payload)

    def test_administration_workgroup_includes_itself(self) -> None:
        workgroups = [
            {"id": "admin-1", "name": "Administration", "owner_id": "u1", "created_at": "2026-01-01T00:00:00Z"},
            {"id": "wg-2", "name": "Other", "owner_id": "u1", "created_at": "2026-01-02T00:00:00Z"},
        ]
        files = workgroup_storage_files(workgroups, {})
        paths = {f["path"] for f in files}

        self.assertIn(f"{WORKGROUP_STORAGE_ROOT}/admin-1/workgroup.json", paths)
        self.assertIn(f"{WORKGROUP_STORAGE_ROOT}/wg-2/workgroup.json", paths)

    def test_readme_lists_all_workgroups(self) -> None:
        workgroups = [
            {"id": "wg-a", "name": "Alpha", "owner_id": "u1", "created_at": "2026-01-01T00:00:00Z"},
            {"id": "wg-b", "name": "Beta", "owner_id": "u2", "created_at": "2026-01-02T00:00:00Z"},
        ]
        files = workgroup_storage_files(workgroups, {})
        readme = next(f for f in files if f["path"].endswith("README.md"))

        self.assertIn("Alpha", readme["content"])
        self.assertIn("Beta", readme["content"])
        self.assertIn("wg-a", readme["content"])
        self.assertIn("wg-b", readme["content"])
