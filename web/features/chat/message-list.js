// Reconciled message list renderer.
// Efficiently updates the DOM when messages change using per-element reconciliation.

import { bus } from '../../core/bus.js';
import { createMessageElement, updateMessageElement } from './message-row.js';
import { syncThinkingState, renderThinkingIndicator } from './thinking.js';
import { parseAsUTC } from '../../core/utils.js';

let _store = null;

// Track rendered message IDs for animation detection and reconciliation
let _renderedIds = new Set();
let _renderedConvId = null;

// Track whether user has scrolled up (to suppress auto-scroll)
let _userScrolledUp = false;

/** Check if two consecutive messages should be grouped (same sender, within 5 min). */
function shouldGroup(prev, curr) {
  if (!prev) return false;
  if (prev.sender_type !== curr.sender_type) return false;
  if (prev.sender_type === 'system') return false;
  if (prev.sender_agent_id !== curr.sender_agent_id) return false;
  if (prev.sender_user_id !== curr.sender_user_id) return false;

  const prevTime = parseAsUTC(prev.created_at).getTime();
  const currTime = parseAsUTC(curr.created_at).getTime();
  return (currTime - prevTime) < 5 * 60 * 1000;
}

/** Reconcile the DOM to match the given message array. */
function reconcileMessages(store, messages) {
  const container = document.getElementById('messages');
  if (!container) return;

  const s = store.get();
  const convId = s.nav.activeConversationId;

  // Detect conversation change
  const isNewConversation = _renderedConvId !== convId;
  const newIds = isNewConversation
    ? new Set()
    : new Set(messages.filter(m => !_renderedIds.has(m.id)).map(m => m.id));

  if (!messages.length) {
    // Remove all message rows (keep thinking rows — they'll be handled separately)
    const rows = container.querySelectorAll('.message-row:not(.thinking)');
    rows.forEach(r => r.remove());
    const emptyEl = container.querySelector('.messages-empty');
    if (!emptyEl) {
      const p = document.createElement('p');
      p.className = 'meta messages-empty';
      p.textContent = 'No messages yet.';
      container.insertBefore(p, container.firstChild);
    }
    _renderedIds = new Set();
    _renderedConvId = convId;
    return;
  }

  // Remove empty-state placeholder if present
  const emptyEl = container.querySelector('.messages-empty');
  if (emptyEl) emptyEl.remove();

  // Build a map of existing message elements by ID
  const existingEls = new Map();
  container.querySelectorAll('.message-row[data-msg-id]:not(.thinking)').forEach(el => {
    existingEls.set(el.dataset.msgId, el);
  });

  // Determine which elements to keep, create, or update
  const newEls = messages.map((message, i) => {
    const isGrouped = shouldGroup(messages[i - 1] || null, message);
    const isNew = newIds.has(message.id);

    if (existingEls.has(message.id)) {
      const el = existingEls.get(message.id);
      updateMessageElement(store, el, message, isGrouped);
      existingEls.delete(message.id);
      return el;
    } else {
      return createMessageElement(store, message, isGrouped, isNew);
    }
  });

  // Remove stale elements (messages that no longer exist)
  existingEls.forEach(el => el.remove());

  // Insert or reorder elements before any thinking rows
  const thinkingRows = [...container.querySelectorAll('.message-row.thinking')];
  const firstThinkingRow = thinkingRows[0] || null;

  newEls.forEach(el => {
    if (!container.contains(el)) {
      container.insertBefore(el, firstThinkingRow);
    } else if (firstThinkingRow && el.compareDocumentPosition(firstThinkingRow) & Node.DOCUMENT_POSITION_PRECEDING) {
      // el is after thinking row — move it before
      container.insertBefore(el, firstThinkingRow);
    }
  });

  // Ensure correct DOM order (insertBefore the next sibling or firstThinkingRow)
  for (let i = 0; i < newEls.length; i++) {
    const el = newEls[i];
    const nextExpected = newEls[i + 1] || firstThinkingRow;
    if (nextExpected && el.nextSibling !== nextExpected) {
      container.insertBefore(el, nextExpected);
    }
  }

  _renderedIds = new Set(messages.map(m => m.id));
  _renderedConvId = convId;
}

/** Auto-scroll to bottom if user hasn't scrolled up. */
function maybeScrollToBottom() {
  const container = document.getElementById('messages');
  if (!container) return;
  if (!_userScrolledUp) {
    container.scrollTop = container.scrollHeight;
  }
}

/** Render the full message list: reconcile + sync thinking + scroll. */
export function renderMessages(store, messages) {
  syncThinkingState(store, messages);
  reconcileMessages(store, messages);
  renderThinkingIndicator(store);
  maybeScrollToBottom();
}

export function initMessageList(store) {
  _store = store;

  const container = document.getElementById('messages');
  if (container) {
    // Detect user scroll-up to suppress auto-scroll
    container.addEventListener('scroll', () => {
      const distanceFromBottom = container.scrollHeight - container.scrollTop - container.clientHeight;
      _userScrolledUp = distanceFromBottom > 80;
    });
  }

  // Re-render when messages change in store
  store.on('conversation.messages', s => {
    const messages = s.conversation.messages || [];
    renderMessages(store, messages);
  });

  // Re-render when tree data loads (agent/member names resolve from treeData)
  store.on('data.treeData', () => {
    const messages = store.get().conversation.messages || [];
    if (messages.length) renderMessages(store, messages);
  });

  // Handle incoming SSE messages
  bus.on('sse:message', ({ conversationId, event }) => {
    const s = store.get();
    if (conversationId !== s.nav.activeConversationId) return;

    const msg = event.message || event;
    if (!msg || !msg.id) return;

    // De-duplicate: skip if already in store
    const existing = s.conversation.messages || [];
    if (existing.some(m => m.id === msg.id)) return;

    store.update(st => {
      st.conversation.messages = [...(st.conversation.messages || []), msg];
    });
    // notify triggers the store.on('conversation.messages') subscriber above
    store.notify('conversation.messages');
  });

  // Handle SSE activity for thinking state
  bus.on('sse:activity', ({ conversationId }) => {
    const s = store.get();
    if (conversationId !== s.nav.activeConversationId) return;
    // thinking.js handles the store update; we just re-render the indicator
    renderThinkingIndicator(store);
  });
}
