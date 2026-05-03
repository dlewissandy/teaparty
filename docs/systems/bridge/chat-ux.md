# Chat UX — One Codepath, Conserved Everywhere

The chat UX is one thing, and it is implemented exactly once.

Every page that shows a chat mounts `teaparty/bridge/static/accordion-chat.js`. Pages do not carry chat DOM, state, or event handlers of their own.

## The rule

```
There is one chat UX implementation. Adding a second one —
even a simpler version, even for a new page, even temporarily —
is prohibited. If you need something that does not fit the shared
implementation, extend the shared implementation or file a ticket
to change the rule. Do not fork.
```

This rule is enforced by `tests/bridge/test_chat_ux_consolidation_400.py`, which asserts that accordion UX symbols exist only in `accordion-chat.js` and not in any HTML page. The test runs in CI and blocks merges on violation.

## Implementation

`accordion-chat.js` defines the complete accordion chat UX:
- Chevron tab (open/close blade)
- Blade header with configurable title
- Filter bar (agent, human, thinking, tools, results, system, state, cost, log)
- Dispatch accordion: nested sections for each agent in the dispatch tree
- Status badges (active/idle)
- iframe chat message list per section
- CloseConversation cascade with auto-parent-activation
- WebSocket subscription for `dispatch_started`, `dispatch_completed`, `session_completed`

## Mounting

```js
var chat = AccordionChat.mount(bladeEl, { convId, title });
```

- `bladeEl` — the `.blade` element (empty shell; module writes the interior)
- `convId` — the conversation ID to chat with; drives routing and dispatch tree
- `title` — displayed in the blade header

The instance exposes:
- `chat.seed(message)` — open the blade and post a message
- `chat.configure({ convId, title })` — switch to a different conversation
- `chat.toggle()` — open/close the blade
- `chat.destroy()` — clean up

## Session ID derivation

The accordion fetches `/api/dispatch-tree/{sessionId}`. The session ID is derived from `convId` by `AccordionChat.deriveSessionId(convId)`, which mirrors `AgentSession._session_key()`:

| convId form | sessionId |
|---|---|
| `om` (bare) | `office-manager` — the OM is a singleton, no qualifier |
| `lead:{name}:{qualifier}` | `{name}-{name}-{qualifier}` |
| `job:{project}:{session_id}` | `{session_id}` — scoped to the job's project lead |
| `config:{...}` | resolves to the `configuration-lead` thread for that entity |

## Page routing table

| Page | convId | Agent |
|---|---|---|
| Home | `om` (bare) | office-manager |
| Management Team config | `om` (bare) — the OM routes configuration intent to the configuration lead internally | office-manager |
| Project Team config | `lead:{slug}-lead:{qualifier}` | {slug}-lead |
| Agent/Workgroup detail | parent project's lead | parent project's lead |
| Job detail | `job:{project}:{session_id}` | project lead for that project |
| Artifacts page | `job:{project}:{session_id}` or `om` depending on the page's mode | project lead or office-manager |

The `om:{qualifier}` form existed in earlier iterations; the OM is now a singleton and uses a bare `om` convId everywhere.
