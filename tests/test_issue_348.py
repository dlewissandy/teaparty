"""Tests for Issue #348: routing table derivation from workgroup config is unspecified.

Acceptance criteria:
1. agent_id format is project-scoped to disambiguate shared workgroup instances across projects
2. routing.md specifies how matrixed (shared) workgroup membership is handled in routing
3. routing.md makes explicit that shared workgroup membership does not create cross-project routes
4. derivation algorithm for the routing table is specified (non-matrixed case — already partly done)
"""
import re
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
_ROUTING_MD = _REPO_ROOT / "docs/proposals/agent-dispatch/references/routing.md"


def _routing_text() -> str:
    return _ROUTING_MD.read_text()


class TestAgentIdProjectScope(unittest.TestCase):
    """agent_id must include project scope so matrixed workgroups don't collide."""

    def test_agent_id_format_includes_project_scope(self):
        """Agent Identity section must specify a project-qualified agent_id format."""
        text = _routing_text()
        # The format {workgroup_name}/{role_name} alone is ambiguous for shared workgroups.
        # The spec must define a project-scoped format.
        self.assertRegex(
            text,
            r"project[_\s-]*(scoped|qualified|name|prefix|identifier)",
            "routing.md must state that agent_id is scoped to the project "
            "(e.g., project-qualified) to disambiguate matrixed workgroup instances"
        )

    def test_agent_id_example_shows_project_prefix(self):
        """A concrete project-scoped agent_id example must appear in routing.md."""
        text = _routing_text()
        # Match patterns like: teaparty/coding-team/lead  OR  project/workgroup/role
        # The examples section currently shows coding-team/lead (no project prefix).
        self.assertRegex(
            text,
            r"\w[\w-]*/[\w-]+/[\w-]+",
            "routing.md must include a project-scoped agent_id example "
            "in the form {project}/{workgroup}/{role}"
        )


class TestMatrixedWorkgroupRouting(unittest.TestCase):
    """routing.md must specify how matrixed workgroups are handled in routing derivation."""

    def test_matrixed_workgroup_section_exists(self):
        """A section or subsection addressing matrixed workgroup routing must be present."""
        text = _routing_text()
        self.assertRegex(
            text,
            r"(?i)matrixed",
            "routing.md must address matrixed workgroup routing — "
            "currently absent, leaving a prerequisite gap for #346"
        )

    def test_shared_membership_does_not_create_cross_project_routes(self):
        """The spec must explicitly state shared membership does not create cross-project routes."""
        text = _routing_text()
        # Look for language saying shared/matrixed membership does NOT route cross-project.
        self.assertRegex(
            text,
            r"(?i)(shared.{0,60}(not|no|does not|never).{0,40}(cross.project|route)|"
            r"(cross.project|route).{0,60}(not|no|does not|never).{0,40}shared)",
            "routing.md must state that shared workgroup membership does not grant "
            "cross-project routing"
        )

    def test_derivation_processes_each_project_independently(self):
        """The derivation algorithm must clarify that routing is scoped per project."""
        text = _routing_text()
        self.assertRegex(
            text,
            r"(?i)(per.project|within.{0,20}project|scoped.{0,20}project|project.{0,20}scope)",
            "routing.md must state that routing derivation is scoped per project, "
            "not across the whole organization"
        )


class TestProjectLeadIdentity(unittest.TestCase):
    """Project lead agent_id must be defined since it is used as a routing hub."""

    def test_project_lead_agent_id_is_defined(self):
        """routing.md must define what a project lead's agent_id looks like."""
        text = _routing_text()
        # Currently the spec references 'project_lead' as a routing hub but never
        # specifies its agent_id format.
        self.assertRegex(
            text,
            r"(?i)project.{0,10}lead.{0,60}agent.?id|agent.?id.{0,60}project.{0,10}lead",
            "routing.md must define the agent_id for the project lead role, "
            "since it is referenced as the cross-workgroup routing hub"
        )
