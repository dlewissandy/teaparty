# Chat Delivery: Fetch-and-Subscribe Atomicity

**Status:** implemented (issue #398)

## Contract

> Every chat message is delivered to every connected client **exactly once**,
> across the join between the initial HTTP load and the live WebSocket stream.
> The client does not filter or dedup inbound `message` events.

The delivery channel is not racy. Clients that receive a message may render
it unconditionally; there is no client-side state they must consult to decide
whether to show it.

## Participants

- **`SqliteMessageBus`** (`teaparty/messaging/conversations.py`) — stores
  rows, exposes `receive_since_cursor(cid, cursor) -> (messages, new_cursor)`.
- **Bridge HTTP handler** (`_handle_conversation_get` in
  `teaparty/bridge/server.py`) — reads the bus and returns
  `{messages, cursor}` captured in the same read.
- **Bridge WebSocket handler** (`_handle_websocket`) — parses `subscribe` /
  `unsubscribe` / `ping` frames, delegates to the relay.
- **`MessageRelay`** (`teaparty/bridge/message_relay.py`) — holds per-
  `(connection, conversation)` cursors, dispatches catch-up replay and live
  polling under a single asyncio lock.
- **Client** (`teaparty/bridge/static/chat.html`) — performs the handshake,
  never filters.

## Cursor representation

Cursors are opaque to the client. On the wire:

```
{timestamp:.9f}:{id}
```

- `timestamp` is the row's `REAL NOT NULL` column, formatted with nine decimal
  digits to preserve precision.
- `id` is the UUID primary key of the last row returned.
- An empty cursor string means "from the beginning of the conversation."

The bus's read query defines a stable total order over rows:

```sql
ORDER BY timestamp ASC, id ASC
```

The cursor advance query matches that order:

```sql
WHERE conversation = ?
  AND (timestamp > ? OR (timestamp = ? AND id > ?))
```

Equal-timestamp rows (which do happen — text-stream events written tightly
from the same agent) are disambiguated by `id`, giving a deterministic
resume point.

## The handshake

```
┌────────┐               ┌────────┐                 ┌────────┐
│ Client │               │ Bridge │                 │  Bus   │
└────┬───┘               └───┬────┘                 └────┬───┘
     │                       │                           │
     │ GET /api/conv/{cid}   │                           │
     ├──────────────────────>│                           │
     │                       │  receive_since_cursor('') │
     │                       ├──────────────────────────>│
     │                       │  (rows, cursor₀)          │
     │                       │<──────────────────────────┤
     │ {messages, cursor₀}   │                           │
     │<──────────────────────┤                           │
     │                       │                           │
     │ WS connect            │                           │
     ├──────────────────────>│                           │
     │                       │                           │
     │ {subscribe, cid,      │                           │
     │  since_cursor=c₀}     │                           │
     ├──────────────────────>│                           │
     │                       │  receive_since_cursor(c₀) │
     │                       ├──────────────────────────>│
     │                       │  (gap_rows, cursor₁)      │
     │                       │<──────────────────────────┤
     │ message × gap_rows    │                           │
     │<──────────────────────┤                           │
     │                       │                           │
     │         ... relay polls and dispatches live ...   │
     │ message × live rows   │                           │
     │<──────────────────────┤                           │
```

Any row M with timestamp `ts(M)` that is committed to the bus between the
HTTP read and the subscribe catch-up read is captured by **exactly one** of
the two reads: it is either `ts(M) ≤ ts(c₀)` (so the HTTP fetch returned it
and the subscribe cursor excludes it) or `ts(M) > ts(c₀)` (so the HTTP fetch
did not return it and the subscribe catch-up does). The cursor is the
watermark that makes these two sets disjoint.

## Mutual exclusion

`MessageRelay` holds a single `asyncio.Lock` that serializes:

- `subscribe(conn, cid, since_cursor)` — catch-up replay + cursor install.
- `unsubscribe(conn, cid)` — cursor removal.
- `_dispatch_messages()` — live polling of every active subscription.

A subscribe-while-polling race is impossible: the catch-up and the first
live poll cannot both read from the same cursor value, because the subscribe
advances the cursor before releasing the lock.

## Escalation events

`awaiting_input` transitions are now first-class events:

- `input_requested` on False → True (unchanged from the pre-#398 behavior).
- `escalation_cleared` on True → False (new). The dashboard reacts to this
  to clear the attention dot. `index.html` no longer infers escalation state
  by inspecting chat `message` broadcasts — in fact `index.html` does not
  subscribe to any conversation.

Both events are global: they flow through the bridge's broadcast callback
and reach every connected client, independent of subscription state.

## What the client does not do

- No id-based dedup of inbound `message` events.
- No substring/timestamp-based dedup.
- No global "last seen" cursor shared across conversations.
- No inspection of a `message` event to infer conversation-level state
  (escalation, completion, etc.) — those are their own event types.

The only exception is the send-side reconciliation of the user's own
optimistic entry: when `sendMessage` posts a new human message, it appends
an optimistic DOM entry and binds it to the server's authoritative message
id via the POST response. When the corresponding `message` event arrives
on the subscribe stream, the client matches by id and replaces the
optimistic entry in place instead of appending a duplicate. This is
reconciliation — match-then-replace of a known local placeholder — not a
filter against "already seen" state.
