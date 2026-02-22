// Chat panel: main coordinator for the chat view.
// Handles conversation loading, SSE connection, view switching, and wires up sub-components.

import { api } from '../../core/api.js';
import { bus } from '../../core/bus.js';
import { escapeHtml } from '../../core/utils.js';
import { flash } from '../../components/shared/flash.js';
import { connectSSE, disconnectSSE } from '../../core/sse.js';
import { initChatHeader } from './chat-header.js';
import { initMessageList } from './message-list.js';
import { initComposer } from './composer.js';
import { initThinking } from './thinking.js';

let _store = null;

// ─── View switching ────────────────────────────────────────────────────────

function showChatView() {
  const views = ['home-view', 'agent-profile-view', 'partner-profile-view', 'workgroup-profile-view', 'directory-view', 'org-dashboard-view', 'org-settings-view', 'create-project-form'];
  for (const id of views) { document.getElementById(id)?.classList.add('hidden'); }
  document.getElementById('chat-view')?.classList.remove('hidden');
}

function showHomeView() {
  const views = ['chat-view', 'agent-profile-view', 'partner-profile-view', 'workgroup-profile-view', 'directory-view', 'org-dashboard-view', 'org-settings-view', 'create-project-form'];
  for (const id of views) { document.getElementById(id)?.classList.add('hidden'); }
  document.getElementById('home-view')?.classList.remove('hidden');
}

export function showOrgDashboardView() {
  const views = ['chat-view', 'home-view', 'agent-profile-view', 'partner-profile-view', 'workgroup-profile-view', 'directory-view', 'org-settings-view', 'create-project-form'];
  for (const id of views) { document.getElementById(id)?.classList.add('hidden'); }
  document.getElementById('org-dashboard-view')?.classList.remove('hidden');
}

// ─── Conversation loading ──────────────────────────────────────────────────

async function loadMessages(store, conversationId) {
  try {
    const messages = await api(`/api/conversations/${conversationId}/messages`);
    const s = store.get();
    // Only apply if still the active conversation
    if (s.nav.activeConversationId !== conversationId) return;
    store.update(st => { st.conversation.messages = messages; });
    store.notify('conversation.messages');
  } catch (err) {
    console.error('Failed to load messages:', err);
    flash('Failed to load messages', 'error');
  }
}

async function loadUsage(store, conversationId) {
  try {
    const usage = await api(`/api/conversations/${conversationId}/usage`);
    const s = store.get();
    if (s.nav.activeConversationId !== conversationId) return;
    store.update(st => { st.conversation.usage = usage; });
  } catch {
    // Non-critical — ignore
  }
}

async function loadTeamRoster(store, conversationId) {
  try {
    const roster = await api(`/api/conversations/${conversationId}/participants`);
    const s = store.get();
    if (s.nav.activeConversationId !== conversationId) return;
    store.update(st => { st.conversation.teamRoster = roster; });
    renderTeamRoster(roster);
    // Re-render messages so agent names resolve from roster
    store.notify('conversation.messages');
  } catch {
    // Non-critical
  }
}

function renderTeamRoster(roster) {
  const rosterEl = document.getElementById('chat-team-roster');
  if (!rosterEl) return;

  const { users = [], agents = [] } = roster || {};
  if (agents.length < 2) {
    rosterEl.innerHTML = '';
    return;
  }

  const chips = [
    ...agents.map(a => `<span class="team-roster-chip agent">${escapeHtml(a.name)}${a.is_lead ? ' \u2605' : ''}</span>`),
    ...users.map(u => `<span class="team-roster-chip">${escapeHtml(u.name || u.email)}</span>`),
  ].join('');

  rosterEl.innerHTML = `<div class="team-roster"><span class="team-roster-label">Team:</span>${chips}</div>`;
}

// ─── Conversation selection ────────────────────────────────────────────────

async function onConversationSelected(store, { workgroupId, conversationId }) {
  // Clear previous state
  disconnectSSE();
  store.update(st => {
    st.nav.activeWorkgroupId = workgroupId;
    st.nav.activeConversationId = conversationId;
    st.conversation.messages = [];
    st.conversation.usage = null;
    st.conversation.teamRoster = [];
    // Clear thinking state for this conversation
    delete st.conversation.thinkingByConversation[conversationId];
  });
  store.notify('conversation.messages');
  store.notify('nav.activeConversationId');

  showChatView();

  // Parallel loads
  await Promise.all([
    loadMessages(store, conversationId),
    loadUsage(store, conversationId),
    loadTeamRoster(store, conversationId),
  ]);

  // Connect SSE for live updates
  connectSSE(conversationId);
}

// ─── Init ──────────────────────────────────────────────────────────────────

export function initChatPanel(store) {
  _store = store;

  // Init sub-components
  initChatHeader(store);
  initMessageList(store);
  initComposer(store);
  initThinking(store);

  // Listen for conversation selection from navigation
  bus.on('nav:conversation-selected', ({ workgroupId, conversationId }) => {
    onConversationSelected(store, { workgroupId, conversationId });
  });

  // Reload messages when conversation data changes (archive, job complete, etc.)
  bus.on('chat:conversation-updated', ({ convId }) => {
    const s = store.get();
    if (s.nav.activeConversationId === convId) {
      loadMessages(store, convId);
    }
  });

  // After send, reload to get server-assigned IDs (SSE may arrive first, that's fine)
  bus.on('chat:message-sent', ({ convId }) => {
    const s = store.get();
    if (s.nav.activeConversationId === convId) {
      setTimeout(() => {
        if (store.get().nav.activeConversationId === convId) {
          loadMessages(store, convId).catch(() => {});
          loadUsage(store, convId).catch(() => {});
        }
      }, 500);
    }
  });

  // Listen for home navigation
  bus.on('nav:home', () => {
    disconnectSSE();
    store.update(st => {
      st.nav.activeConversationId = '';
      st.nav.activeWorkgroupId = '';
      st.conversation.messages = [];
      st.conversation.usage = null;
    });
    store.notify('nav.activeConversationId');
    store.notify('conversation.messages');
    showHomeView();
  });

  // React to store-driven conversation changes (e.g. from URL routing)
  store.on('nav.activeConversationId', s => {
    const convId = s.nav.activeConversationId;
    if (convId) {
      showChatView();
    } else {
      // Don't override other content views (profile, dashboard, etc.)
      const contentViews = [
        'agent-profile-view', 'partner-profile-view', 'workgroup-profile-view',
        'directory-view', 'org-dashboard-view', 'org-settings-view', 'create-project-form',
      ];
      const anyShowing = contentViews.some(id => {
        const el = document.getElementById(id);
        return el && !el.classList.contains('hidden');
      });
      if (!anyShowing) {
        showHomeView();
      }
    }
  });

  // Right panel toggle: update active tab indicator
  store.on('panels.rightPanelOpen', s => {
    const panel = document.getElementById('right-panel');
    if (!panel) return;
    panel.classList.toggle('open', s.panels.rightPanelOpen);

    // Activate the correct tab
    const tabs = panel.querySelectorAll('.right-panel-tab');
    const contents = panel.querySelectorAll('.right-panel-content');
    const activeTab = s.panels.rightPanelTab || 'files';

    tabs.forEach(tab => {
      const isActive = tab.dataset.tab === activeTab;
      tab.classList.toggle('active', isActive);
      tab.setAttribute('aria-selected', String(isActive));
    });

    contents.forEach(content => {
      const isActive = content.dataset.tab === activeTab;
      content.classList.toggle('hidden', !isActive);
    });
  });

  // Right panel close button
  document.getElementById('right-panel-close')?.addEventListener('click', () => {
    store.update(st => { st.panels.rightPanelOpen = false; });
    store.notify('panels.rightPanelOpen');
  });

  // Right panel tab switching
  document.getElementById('right-panel')?.addEventListener('click', e => {
    const tab = e.target.closest('.right-panel-tab');
    if (!tab) return;
    const tabName = tab.dataset.tab;
    if (!tabName) return;
    store.update(st => {
      st.panels.rightPanelOpen = true;
      st.panels.rightPanelTab = tabName;
    });
    store.notify('panels.rightPanelOpen');
  });

  // Initial state
  const s = store.get();
  if (s.nav.activeConversationId) {
    showChatView();
  } else {
    showHomeView();
  }
}
