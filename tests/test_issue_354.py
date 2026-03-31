"""Tests for Issue #354: Chat filter state not applied on initial render.

Acceptance criteria:
1. On first render, only messages matching the active filter toggles are shown
2. thinking/system/cost/log messages are hidden unless those buttons are toggled on
3. Behavior on subsequent filter-toggle clicks (refilter) is unchanged
"""
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
_CHAT_HTML = _REPO_ROOT / 'bridge' / 'static' / 'chat.html'


def _read_chat() -> str:
    return _CHAT_HTML.read_text()


def _get_function_body(html: str, fn_name: str) -> str:
    fn_start = html.find('function ' + fn_name + '(')
    assert fn_start >= 0, f'{fn_name} not found'
    brace_start = html.find('{', fn_start)
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


class TestRenderMainAreaDoesNotRenderMessagesBeforeDOMIsReady(unittest.TestCase):
    """renderMainArea must not call renderMessages during HTML string construction."""

    def test_renderMainArea_does_not_inline_renderMessages_call(self):
        """renderMainArea must not call renderMessages() while building the innerHTML string.

        Calling renderMessages() during string construction means filterMessages() runs
        before the filter buttons are in the DOM, so all messages pass through unfiltered.
        """
        html = _read_chat()
        body = _get_function_body(html, 'renderMainArea')
        # The innerHTML assignment ends with the closing semicolon. Everything before
        # 'refilter()' is the string-construction block. renderMessages must not appear
        # in the innerHTML assignment — only refilter() should populate the messages div.
        #
        # Find the innerHTML assignment block (between 'innerHTML =' and the matching ';')
        inner_start = body.find('innerHTML =')
        self.assertGreater(inner_start, -1, 'renderMainArea must set innerHTML')
        # Find the end of the assignment (first ';' after the string closes)
        inner_end = body.find(';', inner_start)
        self.assertGreater(inner_end, -1)
        assignment_block = body[inner_start:inner_end]
        self.assertNotIn('renderMessages', assignment_block,
                         'renderMainArea must not call renderMessages() inside the innerHTML '
                         'string — the DOM is not yet updated so filterMessages finds no buttons')

    def test_renderMainArea_inserts_empty_messages_div(self):
        """renderMainArea must insert an empty .chat-messages div, not pre-populated content."""
        html = _read_chat()
        body = _get_function_body(html, 'renderMainArea')
        # The div must be empty (immediately closed) in the innerHTML string
        self.assertIn('chat-messages"></div>', body,
                      'chat-messages div must be empty in the innerHTML assignment — '
                      'message population happens via refilter() after DOM update')

    def test_renderMainArea_calls_refilter_after_setting_innerHTML(self):
        """renderMainArea must call refilter() after setting innerHTML so the DOM has filter buttons."""
        html = _read_chat()
        body = _get_function_body(html, 'renderMainArea')
        # refilter() must be called — and it must come after the innerHTML assignment
        inner_start = body.find('innerHTML =')
        inner_end = body.find(';', inner_start)
        # refilter must appear after the assignment, not inside it
        refilter_pos = body.find('refilter()', inner_end)
        self.assertGreater(refilter_pos, -1,
                           'renderMainArea must call refilter() after setting innerHTML')


class TestFilterStateAppliedOnInitialRender(unittest.TestCase):
    """The initial render must respect the default filter state (agent + human on)."""

    def test_refilter_is_the_sole_message_populator_in_renderMainArea(self):
        """Only refilter() populates the messages div — not renderMessages directly."""
        html = _read_chat()
        body = _get_function_body(html, 'renderMainArea')
        # renderMessages must not appear anywhere in renderMainArea
        self.assertNotIn('renderMessages', body,
                         'renderMainArea must delegate message rendering entirely to refilter(), '
                         'not call renderMessages() directly')

    def test_refilter_reads_filter_buttons_from_dom(self):
        """refilter must call filterMessages which queries live DOM for filter state."""
        html = _read_chat()
        body = _get_function_body(html, 'refilter')
        self.assertIn('renderMessages', body,
                      'refilter must call renderMessages (which uses filterMessages)')

    def test_filterMessages_has_no_dom_fallthrough(self):
        """filterMessages must not have a fallthrough that returns all messages unfiltered.

        The original bug was: if no .filter-btn buttons found in DOM, return all messages.
        Issue #352 removes this by decoupling filter state from DOM — activeFilters is
        the authoritative source and is always initialized before filterMessages is called.
        """
        html = _read_chat()
        body = _get_function_body(html, 'filterMessages')
        self.assertNotIn('!btns.length', body,
                         'filterMessages must not have a no-buttons-in-DOM guard — '
                         'activeFilters is the authoritative source, not DOM state')
        self.assertNotIn('querySelectorAll', body,
                         'filterMessages must not query the DOM for filter state')


class TestRefilterBehaviorUnchanged(unittest.TestCase):
    """Clicking filter toggle buttons must still work correctly after this fix."""

    def test_filter_buttons_still_call_refilter_on_click(self):
        """Filter toggle buttons must still call refilter() on click."""
        html = _read_chat()
        body = _get_function_body(html, 'renderMainArea')
        # The filter buttons call refilter
        self.assertIn('refilter()', body,
                      'Filter toggle buttons must call refilter() via onclick')

    def test_refilter_function_exists(self):
        """refilter() function must exist."""
        html = _read_chat()
        self.assertIn('function refilter()', html,
                      'refilter() function must be defined')


if __name__ == '__main__':
    unittest.main()
