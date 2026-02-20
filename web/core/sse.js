// SSE connection manager.
// Manages per-conversation EventSource connections and dispatches events through the bus.

import { bus } from './bus.js';

let _store = null;
let _eventSource = null;
let _conversationId = null;

export function initSSE(store) {
  _store = store;
}

export function connectSSE(conversationId) {
  disconnectSSE();
  const token = _store?.get().auth.token;
  if (!token || !conversationId) return;

  const url = `/api/conversations/${encodeURIComponent(conversationId)}/events?token=${encodeURIComponent(token)}`;
  const es = new EventSource(url);
  _eventSource = es;
  _conversationId = conversationId;

  es.onmessage = (evt) => {
    try {
      const event = JSON.parse(evt.data);
      handleSSEEvent(conversationId, event);
    } catch (_) { /* ignore parse errors */ }
  };

  es.onerror = () => {
    if (es.readyState === EventSource.CLOSED) {
      disconnectSSE();
    }
  };
}

export function disconnectSSE() {
  if (_eventSource) {
    _eventSource.close();
    _eventSource = null;
  }
  _conversationId = null;
}

function handleSSEEvent(conversationId, event) {
  const state = _store?.get();
  if (!state || conversationId !== state.nav.activeConversationId) return;

  if (event.type === 'activity') {
    bus.emit('sse:activity', { conversationId, event });
    return;
  }

  if (event.type === 'message') {
    bus.emit('sse:message', { conversationId, event });
    return;
  }
}

export function getSSEConversationId() {
  return _conversationId;
}
