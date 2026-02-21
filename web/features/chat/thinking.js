// Thinking indicator: shows animated dots while agents are composing a reply.
// Renders per-agent "thinking" rows at the bottom of the messages container.

import { escapeHtml } from '../../core/utils.js';
import { agentName } from '../../components/shared/identity.js';
import { generateBotSvg } from '../../components/shared/avatar.js';
import { bus } from '../../core/bus.js';

let _store = null;

/** Phase text labels for SSE activity events. */
function phaseStatusText(phase, detail) {
  if (phase === 'probing') return 'evaluating...';
  if (phase === 'reading' && detail) return `reading ${detail}...`;
  if (phase === 'reading') return 'reading...';
  if (phase === 'analyzing') return 'analyzing...';
  if (phase === 'writing' && detail) return `writing ${detail}...`;
  if (phase === 'writing') return 'writing...';
  if (phase === 'testing') return 'running tests...';
  if (phase === 'tool' && detail) {
    const fileMatch = detail.match(/([^\s/]+\.\w+)$/);
    if (fileMatch) return `working on ${fileMatch[1]}...`;
    return `running ${detail}...`;
  }
  if (phase === 'composing') return 'composing reply...';
  return 'thinking...';
}

/** Build a single thinking row HTML for one agent. */
function buildThinkingRowHtml(name, avatarContent, statusText) {
  return `
    <article class="message-row agent thinking">
      <div class="avatar avatar-agent avatar-glow">${avatarContent}</div>
      <div class="message-body">
        <div class="message-meta">
          <span class="sender agent-name">${escapeHtml(name)}</span>
          <span class="thinking-dots" aria-hidden="true"><span></span><span></span><span></span></span>
          <span class="thinking-phase">${escapeHtml(statusText)}</span>
        </div>
      </div>
    </article>
  `;
}

/** Render all thinking indicator rows into the messages container. */
export function renderThinkingIndicator(store) {
  const s = store.get();
  const wgId = s.nav.activeWorkgroupId;
  const convId = s.nav.activeConversationId;

  // Remove existing thinking rows
  const container = document.getElementById('messages');
  if (!container) return;

  const existing = container.querySelectorAll('.message-row.thinking');
  existing.forEach(el => el.remove());

  if (!convId) return;
  const pending = s.conversation.thinkingByConversation[convId];
  if (!pending) return;

  const wgData = s.data.treeData[wgId];
  const liveActivity = pending.liveActivity;

  let html = '';

  if (liveActivity && liveActivity.length) {
    html = liveActivity.map(entry => {
      const name = entry.agent_name || agentName(wgId, entry.agent_id);
      const thinkingAgent = wgData?.agents?.find(a => a.id === entry.agent_id);
      const avatarContent = thinkingAgent?.image
        ? `<img src="${escapeHtml(thinkingAgent.image)}" alt="" />`
        : generateBotSvg(name);
      const statusText = phaseStatusText(entry.phase, entry.detail);
      return buildThinkingRowHtml(name, avatarContent, statusText);
    }).join('');
  } else if (pending.agentIds && pending.agentIds.length) {
    html = pending.agentIds.map(agentId => {
      const name = agentName(wgId, agentId);
      const thinkingAgent = wgData?.agents?.find(a => a.id === agentId);
      const avatarContent = thinkingAgent?.image
        ? `<img src="${escapeHtml(thinkingAgent.image)}" alt="" />`
        : generateBotSvg(name);
      return buildThinkingRowHtml(name, avatarContent, 'composing reply...');
    }).join('');
  }

  if (html) {
    const temp = document.createElement('div');
    temp.innerHTML = html;
    while (temp.firstChild) container.appendChild(temp.firstChild);
  }
}

/** Clear expired thinking state (timeout checks). Called on each messages render. */
export function syncThinkingState(store, messages) {
  const s = store.get();
  const convId = s.nav.activeConversationId;
  if (!convId) return;

  const pending = s.conversation.thinkingByConversation[convId];
  if (!pending) return;

  // Inactivity timeout: 60s
  const inactiveMs = Date.now() - (pending.lastActivityAtMs || pending.startedAtMs);
  if (inactiveMs > 60000) {
    store.update(st => { delete st.conversation.thinkingByConversation[convId]; });
    store.notify('conversation.thinkingByConversation');
    return;
  }

  // Hard cap: 5 minutes
  if (Date.now() - pending.startedAtMs > 300000) {
    store.update(st => { delete st.conversation.thinkingByConversation[convId]; });
    store.notify('conversation.thinkingByConversation');
    return;
  }

  // Clear when agent reply has arrived
  const hasAgentReply = messages.some(msg => {
    if (msg.sender_type !== 'agent') return false;
    if (msg.response_to_message_id === pending.triggerMessageId) return true;
    const createdMs = new Date(msg.created_at).getTime();
    return createdMs > pending.triggerCreatedAtMs;
  });

  if (hasAgentReply) {
    const recentActivityMs = pending.lastActivityAtMs
      ? Date.now() - pending.lastActivityAtMs
      : Infinity;
    if (recentActivityMs > 15000) {
      store.update(st => { delete st.conversation.thinkingByConversation[convId]; });
      store.notify('conversation.thinkingByConversation');
    }
  }
}

export function initThinking(store) {
  _store = store;

  // Re-render thinking rows when thinking state changes
  store.on('conversation.thinkingByConversation', () => {
    renderThinkingIndicator(store);
  });

  // Update live activity phase from SSE
  bus.on('sse:activity', ({ conversationId, event }) => {
    const s = store.get();
    if (conversationId !== s.nav.activeConversationId) return;

    const pending = s.conversation.thinkingByConversation[conversationId];
    if (!pending) return;

    // Parse activity entries from event
    const activities = Array.isArray(event.activities) ? event.activities
      : event.agent_id ? [{ agent_id: event.agent_id, agent_name: event.agent_name, phase: event.phase, detail: event.detail }]
      : [];

    if (!activities.length) return;

    store.update(st => {
      const p = st.conversation.thinkingByConversation[conversationId];
      if (!p) return;
      p.liveActivity = activities;
      p.lastActivityAtMs = Date.now();
    });
    store.notify('conversation.thinkingByConversation');
  });
}
