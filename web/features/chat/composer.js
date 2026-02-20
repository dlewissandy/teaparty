// Message composer: textarea input, send button, file context display, thinking kickoff.

import { api } from '../../core/api.js';
import { bus } from '../../core/bus.js';
import { escapeHtml } from '../../core/utils.js';
import { flash } from '../../components/shared/flash.js';

let _store = null;

// ─── Thinking state kickoff ────────────────────────────────────────────────

function startThinking(store, message) {
  const s = store.get();
  const wgId = s.nav.activeWorkgroupId;
  const convId = s.nav.activeConversationId;
  const data = s.data.treeData[wgId];
  const conversation = data?.jobs.find(c => c.id === convId) || data?.directs.find(c => c.id === convId);
  if (!conversation || !data) return;

  let agentIds = [];
  if (conversation.kind === 'direct' && conversation.topic.startsWith('dma:')) {
    agentIds = [conversation.topic.split(':')[2]].filter(Boolean);
  } else if (conversation.kind === 'admin') {
    agentIds = (data.agents || []).filter(a => a.description === '__system_admin_agent__').map(a => a.id);
  } else if (conversation.kind === 'job' || conversation.kind === 'engagement') {
    // Show the lead agent thinking, or first non-admin agent
    const jobAgents = (data.agents || []).filter(a => a.description !== '__system_admin_agent__');
    const lead = jobAgents.find(a => a.is_lead);
    agentIds = lead ? [lead.id] : jobAgents.length ? [jobAgents[0].id] : [];
  } else {
    const lead = (data.agents || []).find(a => a.is_lead);
    agentIds = lead ? [lead.id] : [];
  }

  if (!agentIds.length) return;

  const triggerCreatedAtMs = message.created_at
    ? new Date(message.created_at).getTime()
    : Date.now();

  store.update(st => {
    st.conversation.thinkingByConversation[convId] = {
      triggerMessageId: message.id,
      triggerCreatedAtMs,
      startedAtMs: Date.now(),
      lastActivityAtMs: Date.now(),
      agentIds,
      liveActivity: null,
    };
  });
  store.notify('conversation.thinkingByConversation');
}

// ─── File context display ──────────────────────────────────────────────────

function updateFileContextBanner(store) {
  const s = store.get();
  const banner = document.getElementById('composer-file-context');
  if (!banner) return;

  const wgId = s.nav.activeWorkgroupId;
  const wgData = s.data.treeData[wgId];
  const selectedFileId = s.panels.rightPanelOpen
    ? (s.panels._selectedFileId || '')
    : '';

  if (!selectedFileId || !wgData) {
    banner.classList.add('hidden');
    banner.innerHTML = '';
    return;
  }

  const files = wgData.workgroup?.files || [];
  const file = files.find(f => f.id === selectedFileId);
  if (!file) {
    banner.classList.add('hidden');
    return;
  }

  banner.classList.remove('hidden');
  banner.innerHTML = `
    <span class="file-context-label">\uD83D\uDCCE ${escapeHtml(file.path)}</span>
    <button type="button" class="file-context-clear" aria-label="Remove file context" data-action="clear-file-context">&times;</button>
  `;
}

// ─── Textarea auto-resize ──────────────────────────────────────────────────

function autoResizeTextarea(textarea) {
  textarea.style.height = 'auto';
  const maxRows = 6;
  const lineHeight = parseInt(getComputedStyle(textarea).lineHeight, 10) || 20;
  const maxHeight = lineHeight * maxRows;
  textarea.style.height = Math.min(textarea.scrollHeight, maxHeight) + 'px';
}

// ─── Send logic ────────────────────────────────────────────────────────────

async function handleSubmit(store, form) {
  const s = store.get();
  const convId = s.nav.activeConversationId;

  if (!convId) {
    flash('Select a conversation first', 'error');
    return;
  }

  const textarea = document.getElementById('message-content');
  const content = textarea?.value.trim() || '';
  if (!content) return;

  // Build full content (no file context wiring here — panels feature handles that)
  const fullContent = content;

  // Optimistic message
  const optimisticId = `local-${crypto.randomUUID()}`;
  const optimisticMsg = {
    id: optimisticId,
    conversation_id: convId,
    sender_type: 'user',
    sender_user_id: s.auth.user?.id || null,
    sender_agent_id: null,
    content,
    requires_response: false,
    response_to_message_id: null,
    created_at: new Date().toISOString(),
  };

  store.update(st => {
    st.conversation.messages = [...(st.conversation.messages || []), optimisticMsg];
  });
  store.notify('conversation.messages');

  // Persist draft in case of error
  sessionStorage.setItem('draft-message', content);
  if (textarea) textarea.value = '';
  if (textarea) autoResizeTextarea(textarea);

  let posted = null;
  try {
    const envelope = await api(`/api/conversations/${convId}/messages`, {
      method: 'POST',
      body: { content: fullContent },
      headers: { 'X-Idempotency-Key': crypto.randomUUID() },
    });

    posted = envelope?.posted;
    sessionStorage.removeItem('draft-message');

    store.update(st => {
      const without = (st.conversation.messages || []).filter(m => m.id !== optimisticId);
      if (posted && posted.conversation_id === convId) {
        const alreadyExists = without.some(m => m.id === posted.id);
        st.conversation.messages = alreadyExists ? without : [...without, posted];
      } else {
        st.conversation.messages = without;
      }
    });
    store.notify('conversation.messages');

    if (posted) {
      startThinking(store, posted);
      bus.emit('chat:message-sent', { convId, message: posted });
    }

  } catch (err) {
    // Rollback optimistic message
    store.update(st => {
      st.conversation.messages = (st.conversation.messages || []).filter(m => m.id !== optimisticId);
    });
    store.notify('conversation.messages');

    if (textarea) {
      textarea.value = sessionStorage.getItem('draft-message') || '';
    }
    sessionStorage.removeItem('draft-message');
    flash(err.message || 'Failed to send message', 'error');
  }
}

// ─── Init ──────────────────────────────────────────────────────────────────

export function initComposer(store) {
  _store = store;

  const form = document.getElementById('message-form');
  const textarea = document.getElementById('message-content');
  const sendBtn = form?.querySelector('.composer-send');

  if (!form || !textarea) return;

  // Auto-resize on input
  textarea.addEventListener('input', () => {
    autoResizeTextarea(textarea);
    updateSendState(store, textarea, sendBtn);
  });

  // Enter to send, Shift+Enter for newline
  textarea.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (!textarea.value.trim()) return;
      form.dispatchEvent(new Event('submit', { cancelable: true }));
    }
  });

  // Form submit
  form.addEventListener('submit', e => {
    e.preventDefault();
    handleSubmit(store, form);
  });

  // Update send button state when conversation changes
  store.on('nav.activeConversationId', () => updateSendState(store, textarea, sendBtn));

  // File context banner clear button
  document.getElementById('composer-file-context')?.addEventListener('click', e => {
    if (e.target.closest('[data-action="clear-file-context"]')) {
      bus.emit('files:clear-context');
    }
  });

  // Initial state
  updateSendState(store, textarea, sendBtn);
}

function updateSendState(store, textarea, sendBtn) {
  if (!sendBtn) return;
  const s = store.get();
  const hasConversation = Boolean(s.nav.activeConversationId);
  const hasContent = Boolean(textarea?.value.trim());
  sendBtn.disabled = !hasConversation || !hasContent;
}
