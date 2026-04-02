"""Tests for Issue #346: bus routing enforcement is asserted but has no implementation.

Acceptance criteria:
1. routing.md specifies what component performs the routing enforcement check
2. routing.md specifies the routing authorization data structure (routing table format)
3. routing.md specifies how the routing table is populated at session start
4. routing.md specifies rejection behavior for unauthorized posts
5. routing.md explicitly acknowledges the enforcement mechanism is NOT YET BUILT —
   the cross-project isolation guarantee is not stated as current behavior
"""
import re
import unittest
from pathlib import Path

_ROUTING_MD = Path(__file__).parent.parent / "docs/proposals/agent-dispatch/references/routing.md"


def _routing_text() -> str:
    return _ROUTING_MD.read_text()


class TestRoutingMdSpecifiesEnforcingComponent(unittest.TestCase):
    """AC1: routing.md must name the component that performs the enforcement check."""

    def test_bus_dispatcher_component_is_named(self):
        """routing.md must name 'bus dispatcher' as the enforcement component."""
        text = _routing_text()
        self.assertIn("bus dispatcher", text.lower(),
                      "routing.md must name the bus dispatcher as the enforcement component")

    def test_dispatcher_is_located_in_orchestrator(self):
        """routing.md must place the bus dispatcher in the orchestrator/ package."""
        text = _routing_text()
        self.assertIn("orchestrator", text,
                      "routing.md must locate the bus dispatcher in orchestrator/")

    def test_dispatcher_is_a_python_class(self):
        """routing.md must describe the dispatcher as a Python class (not a service or process)."""
        text = _routing_text()
        self.assertIn("Python class", text,
                      "routing.md must describe the bus dispatcher as a Python class")

    def test_dispatcher_is_not_a_separate_process(self):
        """routing.md must clarify the dispatcher is not a separate server or process."""
        text = _routing_text()
        self.assertIn("not a separate", text,
                      "routing.md must clarify the dispatcher is not a separate server or process")


class TestRoutingMdSpecifiesDataStructure(unittest.TestCase):
    """AC2: routing.md must specify the data structure representing routing authorization."""

    def test_routing_table_section_exists(self):
        """routing.md must contain a Routing Table Format section."""
        text = _routing_text()
        self.assertIn("Routing Table", text,
                      "routing.md must contain a Routing Table section")

    def test_routing_table_uses_agent_id_pairs(self):
        """routing.md must specify the routing table as (sender_agent_id, recipient_agent_id) pairs."""
        text = _routing_text()
        self.assertIn("sender_agent_id", text,
                      "routing.md must define routing table in terms of sender_agent_id")
        self.assertIn("recipient_agent_id", text,
                      "routing.md must define routing table in terms of recipient_agent_id")

    def test_agent_identity_format_is_specified(self):
        """routing.md must specify the agent_id format as {workgroup_name}/{role_name}."""
        text = _routing_text()
        self.assertIn("workgroup_name", text,
                      "routing.md must specify agent_id format including workgroup_name")
        self.assertIn("role_name", text,
                      "routing.md must specify agent_id format including role_name")

    def test_within_workgroup_pairs_are_defined(self):
        """routing.md must define routing pairs for within-workgroup communication."""
        text = _routing_text()
        self.assertIn("Within-workgroup", text,
                      "routing.md must define within-workgroup routing pairs")

    def test_cross_workgroup_pairs_are_defined(self):
        """routing.md must define routing pairs for cross-workgroup communication."""
        text = _routing_text()
        self.assertIn("Cross-workgroup", text,
                      "routing.md must define cross-workgroup routing pairs")

    def test_cross_project_pairs_are_defined(self):
        """routing.md must define routing pairs for cross-project communication."""
        text = _routing_text()
        self.assertIn("Cross-project", text,
                      "routing.md must define cross-project routing pairs")


class TestRoutingMdSpecifiesTablePopulation(unittest.TestCase):
    """AC3: routing.md must specify how the routing table is populated at session start."""

    def test_table_computed_at_session_start(self):
        """routing.md must state the routing table is computed at session start."""
        text = _routing_text()
        self.assertIn("session start", text,
                      "routing.md must state the routing table is computed at session start")

    def test_workgroup_yaml_is_the_input(self):
        """routing.md must identify workgroup YAML as the input to routing table derivation."""
        text = _routing_text()
        self.assertIn("workgroup YAML", text,
                      "routing.md must identify workgroup YAML as input to routing derivation")

    def test_table_held_in_memory_for_session_duration(self):
        """routing.md must state the routing table is held in memory for the session duration."""
        text = _routing_text()
        self.assertIn("session's duration", text,
                      "routing.md must state the table is held in memory for the session's duration")


class TestRoutingMdSpecifiesRejectionBehavior(unittest.TestCase):
    """AC4: routing.md must specify rejection behavior for unauthorized posts."""

    def test_routing_error_is_named(self):
        """routing.md must name RoutingError as the client-side rejection signal."""
        text = _routing_text()
        self.assertIn("RoutingError", text,
                      "routing.md must name RoutingError as the rejection error type")

    def test_transport_level_rejection_is_specified(self):
        """routing.md must specify transport-level rejection for unauthorized posts."""
        text = _routing_text()
        self.assertIn("transport level", text,
                      "routing.md must specify transport-level rejection for unauthorized posts")

    def test_two_layer_enforcement_is_described(self):
        """routing.md must describe both the Send pre-check and the dispatcher transport check."""
        text = _routing_text()
        self.assertIn("Send", text,
                      "routing.md must describe Send as the client-side pre-check tool")
        self.assertIn("independent enforcement point", text,
                      "routing.md must describe the dispatcher as an independent enforcement point")


class TestRoutingMdAcknowledgesNotYetBuilt(unittest.TestCase):
    """AC5: routing.md must explicitly acknowledge the enforcement mechanism is not yet implemented.

    The cross-project isolation guarantee must not be stated as current behavior.
    This is the core finding of audit item AD-A-004.
    """

    def test_implementation_status_section_exists(self):
        """routing.md must contain an Implementation Status section."""
        text = _routing_text()
        self.assertIn("Implementation Status", text,
                      "routing.md must contain an 'Implementation Status' section acknowledging "
                      "the enforcement mechanism is designed but not yet built")

    def test_not_yet_implemented_is_stated(self):
        """routing.md must explicitly state the enforcement mechanism is not yet implemented."""
        text = _routing_text()
        not_implemented_markers = [
            "not yet implemented",
            "not yet built",
            "pending implementation",
            "has not been implemented",
        ]
        found = any(marker in text.lower() for marker in not_implemented_markers)
        self.assertTrue(found,
                        "routing.md must explicitly state the enforcement mechanism is not yet "
                        "implemented (e.g., 'not yet implemented', 'pending implementation'). "
                        "The cross-project isolation guarantee must not be stated as current behavior.")

    def test_implementation_references_blocking_issues(self):
        """routing.md must reference the issues that will implement routing enforcement."""
        text = _routing_text()
        # Should reference implementation tracking issues (e.g. #345, #348)
        issue_refs = re.findall(r'#\d+', text)
        self.assertTrue(len(issue_refs) >= 1,
                        "routing.md must reference at least one implementation tracking issue "
                        "to show the gap is tracked (e.g., #345, #348)")


if __name__ == '__main__':
    unittest.main()
