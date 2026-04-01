"""Tests for issue #366: Config screen — remove hardcoded Proxy entry from Participants panel.

Acceptance criteria:
1. No hardcoded Proxy entry in participantItems in renderProject()
2. No hardcoded Proxy entry in participantItems in renderGlobal()
3. Participants panel shows humans from the humans: block with their roles
4. Proxy is not listed on any config screen
"""
import os
import re
import unittest

CONFIG_HTML = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    'bridge', 'static', 'config.html',
)


def _read_config():
    with open(CONFIG_HTML) as f:
        return f.read()


def _extract_function(content, fn_name):
    """Extract the body of a named JS function from content."""
    # Match 'function fnName(' or 'fnName = function(' patterns
    pattern = r'function\s+' + re.escape(fn_name) + r'\s*\('
    m = re.search(pattern, content)
    if not m:
        return ''
    start = m.start()
    # Walk forward to find balanced braces
    depth = 0
    i = content.index('{', start)
    while i < len(content):
        if content[i] == '{':
            depth += 1
        elif content[i] == '}':
            depth -= 1
            if depth == 0:
                return content[start:i + 1]
        i += 1
    return content[start:]


class TestNoHardcodedProxyInRenderProject(unittest.TestCase):
    """renderProject() must not push a hardcoded Proxy entry into participantItems."""

    def setUp(self):
        self.content = _read_config()
        self.render_project = _extract_function(self.content, 'renderProject')
        self.assertNotEqual(self.render_project, '',
                            'renderProject() function not found in config.html')

    def test_render_project_does_not_push_proxy_title(self):
        """renderProject() must not push an item with title 'Proxy' into participantItems."""
        # The hardcoded push used '<div class="item-title">Proxy</div>'
        self.assertNotIn(
            '<div class="item-title">Proxy</div>',
            self.render_project,
            'renderProject() must not push a hardcoded Proxy item into participantItems',
        )

    def test_render_project_does_not_declare_proxy_conv_id(self):
        """renderProject() must not declare proxyConvId — it was used only for the removed push."""
        self.assertNotIn(
            'proxyConvId',
            self.render_project,
            'renderProject() must not declare proxyConvId — it served only the removed Proxy push',
        )

    def test_render_project_humans_loop_present(self):
        """renderProject() must iterate over team.humans to build participant items."""
        self.assertIn(
            'team.humans',
            self.render_project,
            'renderProject() must include the team.humans loop to show declared participants',
        )

    def test_render_project_humans_loop_shows_role(self):
        """renderProject() must render each human's role from the humans: block."""
        self.assertIn(
            'h.role',
            self.render_project,
            'renderProject() must display h.role for each human in the participants panel',
        )


class TestNoHardcodedProxyInRenderGlobal(unittest.TestCase):
    """renderGlobal() must not push a hardcoded Proxy entry into participantItems."""

    def setUp(self):
        self.content = _read_config()
        self.render_global = _extract_function(self.content, 'renderGlobal')
        self.assertNotEqual(self.render_global, '',
                            'renderGlobal() function not found in config.html')

    def test_render_global_does_not_push_proxy_title(self):
        """renderGlobal() must not push an item with title 'Proxy' into participantItems."""
        self.assertNotIn(
            '<div class="item-title">Proxy</div>',
            self.render_global,
            'renderGlobal() must not push a hardcoded Proxy item into participantItems',
        )

    def test_render_global_humans_loop_present(self):
        """renderGlobal() must iterate over m.humans to build participant items."""
        self.assertIn(
            'm.humans',
            self.render_global,
            'renderGlobal() must include the m.humans loop to show declared participants',
        )

    def test_render_global_humans_loop_shows_role(self):
        """renderGlobal() must render each human's role from the humans: block."""
        self.assertIn(
            'h.role',
            self.render_global,
            'renderGlobal() must display h.role for each human in the participants panel',
        )


class TestProxyAbsentFromEntireConfigScreen(unittest.TestCase):
    """No config screen function must push a Proxy participant item."""

    def setUp(self):
        self.content = _read_config()

    def test_proxy_title_not_pushed_as_participant_anywhere(self):
        """No function in config.html may push a hardcoded Proxy participant item.

        The Proxy is a runtime concern instantiated from the humans: block; it must
        not appear as a static entry in any config panel.
        """
        # Count occurrences of the hardcoded Proxy title div
        count = self.content.count('<div class="item-title">Proxy</div>')
        self.assertEqual(
            count, 0,
            f'config.html must not contain any hardcoded Proxy participant items, found {count}',
        )


if __name__ == '__main__':
    unittest.main()
