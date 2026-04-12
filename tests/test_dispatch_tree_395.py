"""Specification tests for issue #395: accordion chat blade with dispatch tree.

Tests verify the dispatch tree API endpoint and the accordion behavior
described in the issue's success criteria.
"""
import json
import os
import tempfile
import unittest


def _make_session_dir(base, session_id, agent_name, conversation_map=None,
                      conversation_id='', scope='management'):
    """Create a session directory with metadata.json."""
    session_dir = os.path.join(base, session_id)
    os.makedirs(session_dir, exist_ok=True)
    metadata = {
        'session_id': session_id,
        'agent_name': agent_name,
        'scope': scope,
        'claude_session_id': f'claude-{session_id}',
        'conversation_map': conversation_map or {},
        'conversation_id': conversation_id,
    }
    with open(os.path.join(session_dir, 'metadata.json'), 'w') as f:
        json.dump(metadata, f)
    return session_dir


class TestBuildDispatchTree(unittest.TestCase):
    """The dispatch tree is built from conversation_maps in metadata.json."""

    def _make_sessions_dir(self):
        self._tmpdir = tempfile.mkdtemp()
        return os.path.join(self._tmpdir, 'sessions')

    def tearDown(self):
        import shutil
        if hasattr(self, '_tmpdir'):
            shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _build_tree(self, sessions_dir, root_session_id):
        from teaparty.bridge.state.dispatch_tree import build_dispatch_tree
        return build_dispatch_tree(sessions_dir, root_session_id)

    def test_single_node_tree(self):
        """OM with no dispatches returns a single-node tree."""
        sessions_dir = self._make_sessions_dir()
        _make_session_dir(sessions_dir, 'om-darrell', 'office-manager',
                          conversation_map={})
        tree = self._build_tree(sessions_dir, 'om-darrell')
        self.assertEqual(tree['session_id'], 'om-darrell')
        self.assertEqual(tree['agent_name'], 'office-manager')
        self.assertEqual(tree['children'], [])

    def test_one_child(self):
        """OM dispatches to PM — tree has one child."""
        sessions_dir = self._make_sessions_dir()
        _make_session_dir(sessions_dir, 'om-darrell', 'office-manager',
                          conversation_map={'req-1': 'pm-teaparty'})
        _make_session_dir(sessions_dir, 'pm-teaparty', 'project-manager',
                          conversation_map={})
        tree = self._build_tree(sessions_dir, 'om-darrell')
        self.assertEqual(len(tree['children']), 1)
        self.assertEqual(tree['children'][0]['session_id'], 'pm-teaparty')
        self.assertEqual(tree['children'][0]['agent_name'], 'project-manager')

    def test_nested_dispatch(self):
        """OM → PM → coding-lead — tree is nested two levels deep."""
        sessions_dir = self._make_sessions_dir()
        _make_session_dir(sessions_dir, 'om-darrell', 'office-manager',
                          conversation_map={'req-1': 'pm-teaparty'})
        _make_session_dir(sessions_dir, 'pm-teaparty', 'project-manager',
                          conversation_map={'req-2': 'coding-lead-1'})
        _make_session_dir(sessions_dir, 'coding-lead-1', 'coding-lead',
                          conversation_map={})
        tree = self._build_tree(sessions_dir, 'om-darrell')
        pm = tree['children'][0]
        self.assertEqual(len(pm['children']), 1)
        self.assertEqual(pm['children'][0]['agent_name'], 'coding-lead')

    def test_parallel_dispatch(self):
        """PM dispatches to two agents — both appear as siblings."""
        sessions_dir = self._make_sessions_dir()
        _make_session_dir(sessions_dir, 'om-darrell', 'office-manager',
                          conversation_map={'req-1': 'pm-teaparty'})
        _make_session_dir(sessions_dir, 'pm-teaparty', 'project-manager',
                          conversation_map={
                              'req-2': 'coding-lead-1',
                              'req-3': 'test-eng-1',
                          })
        _make_session_dir(sessions_dir, 'coding-lead-1', 'coding-lead',
                          conversation_map={})
        _make_session_dir(sessions_dir, 'test-eng-1', 'test-engineer',
                          conversation_map={})
        tree = self._build_tree(sessions_dir, 'om-darrell')
        pm = tree['children'][0]
        self.assertEqual(len(pm['children']), 2)
        child_agents = sorted([c['agent_name'] for c in pm['children']])
        self.assertEqual(child_agents, ['coding-lead', 'test-engineer'])

    def test_missing_child_session(self):
        """If a child session_id has no metadata.json, it appears as a stub."""
        sessions_dir = self._make_sessions_dir()
        _make_session_dir(sessions_dir, 'om-darrell', 'office-manager',
                          conversation_map={'req-1': 'missing-session'})
        tree = self._build_tree(sessions_dir, 'om-darrell')
        self.assertEqual(len(tree['children']), 1)
        child = tree['children'][0]
        self.assertEqual(child['session_id'], 'missing-session')
        # Stub should indicate it's unresolvable
        self.assertEqual(child['agent_name'], 'unknown')

    def test_tree_includes_status(self):
        """Each node in the tree has a status field."""
        sessions_dir = self._make_sessions_dir()
        _make_session_dir(sessions_dir, 'om-darrell', 'office-manager',
                          conversation_map={})
        tree = self._build_tree(sessions_dir, 'om-darrell')
        self.assertIn('status', tree)

    def test_resolves_claude_session_uuid(self):
        """conversation_map values are Claude UUIDs, resolved via index."""
        sessions_dir = self._make_sessions_dir()
        # OM's conversation_map points to a Claude UUID, not a dir name
        _make_session_dir(sessions_dir, 'om-darrell', 'office-manager',
                          conversation_map={'req-1': 'uuid-1234-abcd'})
        # Child session dir has a different name but its claude_session_id matches
        child_dir = os.path.join(sessions_dir, 'abc123')
        os.makedirs(child_dir, exist_ok=True)
        with open(os.path.join(child_dir, 'metadata.json'), 'w') as f:
            json.dump({
                'session_id': 'abc123',
                'agent_name': 'jainai-lead',
                'scope': 'management',
                'claude_session_id': 'uuid-1234-abcd',
                'conversation_map': {},
                'conversation_id': '',
            }, f)
        tree = self._build_tree(sessions_dir, 'om-darrell')
        self.assertEqual(len(tree['children']), 1)
        self.assertEqual(tree['children'][0]['agent_name'], 'jainai-lead')


class TestAccordionHTMLPresent(unittest.TestCase):
    """The accordion chat UX is in accordion-chat.js, not inline in index.html."""

    def _read_static(self, filename):
        path = os.path.join(
            os.path.dirname(__file__), '..', 'teaparty', 'bridge',
            'static', filename)
        with open(path) as f:
            return f.read()

    def test_accordion_container_defined_in_shared_module(self):
        """accordion-chat.js creates the dispatch-accordion container (not index.html)."""
        accordion_js = self._read_static('accordion-chat.js')
        self.assertIn(
            'dispatch-accordion', accordion_js,
            "accordion-chat.js must create the dispatch-accordion container"
        )

    def test_accordion_container_absent_from_index_html(self):
        """index.html no longer hardcodes dispatch-accordion — the module creates it."""
        content = self._read_static('index.html')
        self.assertNotIn(
            'dispatch-accordion', content,
            "index.html hardcodes dispatch-accordion — extract to accordion-chat.js"
        )

    def test_no_single_iframe_blade(self):
        """Neither index.html nor config.html uses the old single-iframe blade pattern."""
        for page in ('index.html', 'config.html'):
            content = self._read_static(page)
            self.assertNotIn(
                'blade-iframe', content,
                f"{page} still contains 'blade-iframe' — the old simplified blade was not removed"
            )


if __name__ == '__main__':
    unittest.main()
