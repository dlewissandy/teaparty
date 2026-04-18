# UI Navigation Convention

**Internal navigation is in-place. New tabs are the user's choice via
browser-native gestures, not the app's choice.**

Every clickable element that navigates to another page inside the
TeaParty UI is an `<a href="...">` anchor. The app never calls
`window.open` for internal navigation, and internal anchors never carry
`target="_blank"`. Inline `onclick` handlers must not navigate via
`location.href` assignment — that strips browser-native gestures
(Cmd-click, middle-click) from the element. Assignments to
`location.href` inside plain JS function bodies — e.g. post-fetch
navigation after `POST /api/jobs` — are allowed because there is no
click target to make into an anchor.

Browser-native gestures — `Cmd+click`, `Ctrl+click`, middle-click,
right-click → *Open Link in New Tab* — continue to work exactly as the
browser provides them, and only because every navigating element is an
anchor. The app stays out of the way; if a user wants a new tab, they
know how to get one.

Cards that wrap complex layouts (project headers, configuration rows,
etc.) become anchors with `display:contents` or flex-container styling
so children participate in the card's layout without the anchor box
interfering. Interactive sub-elements that need their own click target
— e.g. catalog toggle buttons — live as siblings outside the anchor,
not as descendants, so they don't compete with anchor activation.

**External links are out of scope for this rule.** Links in rendered
Markdown inside agent message content (the generic `<a>` renderer in
`chat.html`) point at arbitrary user- or agent-supplied URLs and keep
whatever behavior they have today. This is the one allowlisted exception
enforced by `tests/bridge/test_issue_401.py`.

**Regression guard.** `tests/bridge/test_issue_401.py` greps
`teaparty/bridge/static/` for `window.open` and for `target="_blank"`. Any
new match fails the suite; the failure message lists the offending
file:line and points at this document.
