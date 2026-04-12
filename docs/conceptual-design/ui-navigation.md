# UI Navigation Convention

**Internal navigation is in-place. New tabs are the user's choice via
browser-native gestures, not the app's choice.**

Every link or click target that points at another page inside the TeaParty
UI replaces the current page in the same tab. The app never calls
`window.open` for internal navigation, and internal `<a>` tags never carry
`target="_blank"`. Programmatic navigation uses `location.href = url`.

Browser-native gestures for opening a link in a new tab — `Cmd+click`,
`Ctrl+click`, middle-click, right-click → *Open Link in New Tab* — continue
to work exactly as the browser provides them. The app stays out of the
way; if a user wants a new tab, they know how to get one.

**External links are out of scope for this rule.** Links in rendered
Markdown inside agent message content (the generic `<a>` renderer in
`chat.html`) point at arbitrary user- or agent-supplied URLs and keep
whatever behavior they have today. This is the one allowlisted exception
enforced by `tests/bridge/test_issue_401.py`.

**Regression guard.** `tests/bridge/test_issue_401.py` greps
`teaparty/bridge/static/` for `window.open` and for `target="_blank"`. Any
new match fails the suite; the failure message lists the offending
file:line and points at this document.
