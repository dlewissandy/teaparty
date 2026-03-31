"""Tests for Issue #352: Chat default filters not applied on initial load.

Acceptance criteria:
1. A module-level `activeFilters` variable exists, initialized to agent=true, human=true
2. `filterMessages` reads from `activeFilters`, not from DOM `.filter-btn` queries
3. `filterMessages` has no `querySelectorAll` dependency
4. Filter button onclick updates `activeFilters` before calling refilter()
5. `renderMainArea` renders button `on` class by reading `activeFilters`, not hardcoded names
"""
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
_CHAT_HTML = _REPO_ROOT / 'bridge' / 'static' / 'chat.html'


def _read_chat() -> str:
    return _CHAT_HTML.read_text()


def _extract_function_body(html: str, fn_name: str) -> str:
    """Return the body of a top-level JS function (content between outermost braces)."""
    start = html.find(f'function {fn_name}(')
    if start == -1:
        return ''
    brace_start = html.find('{', start)
    depth = 0
    end = brace_start
    for i in range(brace_start, len(html)):
        if html[i] == '{':
            depth += 1
        elif html[i] == '}':
            depth -= 1
            if depth == 0:
                end = i
                break
    return html[brace_start:end]


class TestActiveFiltersModuleVariable(unittest.TestCase):
    """activeFilters module-level variable must exist and default to agent+human."""

    def test_activeFilters_variable_declared_at_module_level(self):
        """A module-level activeFilters variable must be declared in chat.html.

        This variable holds authoritative filter state so filterMessages works
        before any DOM buttons exist.
        """
        html = _read_chat()
        self.assertIn(
            'activeFilters',
            html,
            'chat.html must declare a module-level activeFilters variable',
        )

    def test_activeFilters_initialized_with_agent_true(self):
        """activeFilters must include agent: true in its initializer.

        On initial load, agent messages must be visible by default.
        """
        html = _read_chat()
        # Must have a var/let/const declaration with both agent and human set
        self.assertRegex(
            html,
            r'var\s+activeFilters\s*=\s*\{[^}]*[\'"]?agent[\'"]?\s*:\s*true',
            'activeFilters must be initialized with agent: true',
        )

    def test_activeFilters_initialized_with_human_true(self):
        """activeFilters must include human: true in its initializer.

        On initial load, human messages must be visible by default.
        """
        html = _read_chat()
        self.assertRegex(
            html,
            r'var\s+activeFilters\s*=\s*\{[^}]*[\'"]?human[\'"]?\s*:\s*true',
            'activeFilters must be initialized with human: true',
        )

    def test_activeFilters_other_types_not_defaulted_true(self):
        """Non-default filter types (thinking, tools, etc.) must not be true in initializer.

        On initial load only agent and human messages should be visible.
        """
        html = _read_chat()
        # Find the activeFilters declaration line
        idx = html.find('var activeFilters')
        self.assertGreater(idx, -1, 'activeFilters must be declared')
        # Extract the initializer block (up to closing brace)
        brace_start = html.find('{', idx)
        brace_end = html.find('}', brace_start)
        initializer = html[brace_start:brace_end + 1]
        for name in ('thinking', 'tools', 'results', 'system', 'state', 'cost', 'log'):
            self.assertNotRegex(
                initializer,
                rf"['\"]?{name}['\"]?\s*:\s*true",
                f"activeFilters must not default '{name}' to true",
            )


class TestFilterMessagesDOMIndependence(unittest.TestCase):
    """`filterMessages` must not query the DOM for filter state."""

    def test_filterMessages_does_not_call_querySelectorAll(self):
        """filterMessages must not contain querySelectorAll.

        DOM-based filter reading fails when buttons do not exist yet (initial load).
        """
        html = _read_chat()
        body = _extract_function_body(html, 'filterMessages')
        self.assertNotEqual(body, '', 'filterMessages function must exist')
        self.assertNotIn(
            'querySelectorAll',
            body,
            'filterMessages must not call querySelectorAll — filter state must come from activeFilters',
        )

    def test_filterMessages_does_not_early_return_all_messages(self):
        """filterMessages must not have a fallthrough that returns all messages unfiltered.

        The original bug: if no buttons found, return messages (all unfiltered).
        This guard must be removed — activeFilters makes it unnecessary.
        """
        html = _read_chat()
        body = _extract_function_body(html, 'filterMessages')
        # The fallthrough guard was: if (!btns.length) return messages;
        self.assertNotIn(
            'btns',
            body,
            'filterMessages must not reference btns — DOM-query approach must be replaced',
        )

    def test_filterMessages_reads_from_activeFilters(self):
        """filterMessages must read filter state from the activeFilters module variable."""
        html = _read_chat()
        body = _extract_function_body(html, 'filterMessages')
        self.assertIn(
            'activeFilters',
            body,
            'filterMessages must read filter state from activeFilters, not from the DOM',
        )


class TestFilterButtonOnClickUpdatesActiveFilters(unittest.TestCase):
    """Filter button onclick must update activeFilters before calling refilter()."""

    def test_filter_button_onclick_updates_activeFilters(self):
        """Filter button onclick handler must update activeFilters.

        When a user toggles a filter, activeFilters must be updated so that
        filterMessages reflects the new state immediately.
        """
        html = _read_chat()
        fn_start = html.find('function renderMainArea(')
        self.assertGreater(fn_start, -1, 'renderMainArea must exist')
        body = _extract_function_body(html, 'renderMainArea')
        # The onclick must reference activeFilters
        self.assertIn(
            'activeFilters',
            body,
            'renderMainArea must update activeFilters in the filter button onclick handler',
        )


class TestRenderMainAreaUsesActiveFiltersForButtonState(unittest.TestCase):
    """renderMainArea must render button on-class from activeFilters, not hardcoded names."""

    def test_renderMainArea_does_not_hardcode_agent_human_as_on(self):
        """renderMainArea must not hardcode agent/human as the only active filters.

        If it does, filter state is silently reset on every render (e.g., on conversation switch).
        Instead, it must read from activeFilters to determine which buttons are on.
        """
        html = _read_chat()
        body = _extract_function_body(html, 'renderMainArea')
        # Must not use a ternary that hardcodes 'agent' or 'human' as the only active filters
        self.assertNotRegex(
            body,
            r'''f\s*===\s*['"]agent['"]\s*\|\|\s*f\s*===\s*['"]human['"]''',
            "renderMainArea must not hardcode agent/human as the on filters — use activeFilters[f] instead",
        )

    def test_renderMainArea_determines_on_class_from_activeFilters(self):
        """renderMainArea must use activeFilters[f] to set the button on class."""
        html = _read_chat()
        body = _extract_function_body(html, 'renderMainArea')
        self.assertIn(
            'activeFilters',
            body,
            'renderMainArea must use activeFilters to determine which filter buttons are on',
        )


if __name__ == '__main__':
    unittest.main()
