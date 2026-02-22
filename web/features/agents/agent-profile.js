// Agent profile view: displays agent details in the main content area.
// Listens for nav:agent-selected, renders a read-only profile.

import { bus } from '../../core/bus.js';
import { escapeHtml } from '../../core/utils.js';
import { generateBotSvg } from '../../components/shared/avatar.js';

let _store = null;
let _currentAgentId = '';
let _currentWorkgroupId = '';

function showAgentProfile() {
  const profileView = document.getElementById('agent-profile-view');
  const chatView = document.getElementById('chat-view');
  const homeView = document.getElementById('home-view');
  const directoryView = document.getElementById('directory-view');
  const dashboardView = document.getElementById('org-dashboard-view');
  const settingsView = document.getElementById('org-settings-view');
  if (profileView) profileView.classList.remove('hidden');
  if (chatView) chatView.classList.add('hidden');
  if (homeView) homeView.classList.add('hidden');
  if (directoryView) directoryView.classList.add('hidden');
  if (dashboardView) dashboardView.classList.add('hidden');
  if (settingsView) settingsView.classList.add('hidden');

  // Close the right panel so the profile gets the full content width
  if (_store) {
    const s = _store.get();
    if (s.panels.rightPanelOpen) {
      _store.update(st => { st.panels.rightPanelOpen = false; });
      _store.notify('panels.rightPanelOpen');
    }
  }
}

/** SVG icons for card headers (matches the edit form). */
const CARD_ICONS = {
  prompt: '<svg viewBox="0 0 20 20" fill="none" width="18" height="18"><path d="M4 4h12a1 1 0 011 1v10a1 1 0 01-1 1H4a1 1 0 01-1-1V5a1 1 0 011-1z" stroke="currentColor" stroke-width="1.3"/><path d="M7 8h6M7 11h4" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>',
  config: '<svg viewBox="0 0 20 20" fill="none" width="18" height="18"><circle cx="10" cy="10" r="2" fill="currentColor"/><path d="M10 2v2M10 16v2M2 10h2M16 10h2M4.22 4.22l1.42 1.42M14.36 14.36l1.42 1.42M4.22 15.78l1.42-1.42M14.36 5.64l1.42-1.42" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>',
  tools: '<svg viewBox="0 0 20 20" fill="none" width="18" height="18"><path d="M4 16l3.5-3.5M13.5 3a2.5 2.5 0 010 5H11L8.5 5.5A2.5 2.5 0 0113.5 3z" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/><path d="M4 4l4 4-4.5 4.5a1.5 1.5 0 002 2L10 10l4 4" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  hooks: '<svg viewBox="0 0 20 20" fill="none" width="18" height="18"><path d="M10 3v7l4 4" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/><circle cx="10" cy="10" r="7.5" stroke="currentColor" stroke-width="1.3"/></svg>',
};

function cardHeader(title, iconKey) {
  return `<div class="agent-profile-card-header"><span class="agent-profile-card-icon">${CARD_ICONS[iconKey] || ''}</span><h4 class="agent-profile-card-title">${escapeHtml(title)}</h4></div>`;
}

/** Human-friendly labels for select-style values. */
const MODEL_LABELS = { sonnet: 'Sonnet', opus: 'Opus', haiku: 'Haiku' };
const PERM_LABELS = { default: 'Default', acceptEdits: 'Accept Edits', dontAsk: "Don't Ask", plan: 'Plan' };

function renderProfile(agent) {
  const avatarEl = document.getElementById('agent-profile-avatar');
  const nameEl = document.getElementById('agent-profile-name');
  const subtitleEl = document.getElementById('agent-profile-role');
  const bodyEl = document.getElementById('agent-profile-body');

  if (avatarEl) {
    avatarEl.innerHTML = agent.image
      ? `<img src="${escapeHtml(agent.image)}" alt="" class="agent-profile-avatar-img" />`
      : generateBotSvg(agent.name);
  }
  if (nameEl) nameEl.textContent = agent.name;
  if (subtitleEl) subtitleEl.textContent = agent.description || '';

  if (!bodyEl) return;

  let html = '';

  // Prompt
  if (agent.prompt) {
    html += `
      <div class="agent-profile-card">
        ${cardHeader('Prompt', 'prompt')}
        <div class="agent-profile-card-body">
          <p class="agent-profile-text">${escapeHtml(agent.prompt)}</p>
        </div>
      </div>`;
  }

  // Configuration
  const model = agent.model || 'sonnet';
  const perm = agent.permission_mode || 'default';
  html += `
    <div class="agent-profile-card">
      ${cardHeader('Configuration', 'config')}
      <div class="agent-profile-card-body">
        <div class="agent-profile-kvs">
          <span class="agent-profile-kv"><span class="agent-profile-key">Model</span> ${escapeHtml(MODEL_LABELS[model] || model)}</span>
          <span class="agent-profile-kv"><span class="agent-profile-key">Permissions</span> ${escapeHtml(PERM_LABELS[perm] || perm)}</span>
          ${agent.memory ? `<span class="agent-profile-kv"><span class="agent-profile-key">Memory</span> ${escapeHtml(agent.memory)}</span>` : ''}
          <span class="agent-profile-kv"><span class="agent-profile-key">Background</span> ${agent.background ? 'on' : 'off'}</span>
          <span class="agent-profile-kv"><span class="agent-profile-key">Isolation</span> ${agent.isolation === false ? 'off' : 'on'}</span>
        </div>
      </div>
    </div>`;

  // Tools
  const tools = agent.tools || [];
  if (tools.length) {
    const chips = tools.map(t => `<span class="tool-chip">${escapeHtml(t)}</span>`).join('');
    html += `
      <div class="agent-profile-card">
        ${cardHeader('Tools', 'tools')}
        <div class="agent-profile-card-body">
          <div class="tool-chip-list">${chips}</div>
        </div>
      </div>`;
  }

  // Hooks
  const hooks = agent.hooks;
  if (hooks && typeof hooks === 'object' && Object.keys(hooks).length) {
    html += `
      <div class="agent-profile-card">
        ${cardHeader('Hooks', 'hooks')}
        <div class="agent-profile-card-body">
          <pre class="agent-profile-text agent-profile-hooks-pre">${escapeHtml(JSON.stringify(hooks, null, 2))}</pre>
        </div>
      </div>`;
  }

  bodyEl.innerHTML = html;
}

export function initAgentProfile(store) {
  _store = store;

  // Hide profile when navigating away to an org or home
  bus.on('nav:org-selected', () => {
    const profileView = document.getElementById('agent-profile-view');
    if (profileView) profileView.classList.add('hidden');
    _currentAgentId = '';
    _currentWorkgroupId = '';
  });

  bus.on('nav:home', () => {
    const profileView = document.getElementById('agent-profile-view');
    if (profileView) profileView.classList.add('hidden');
    _currentAgentId = '';
    _currentWorkgroupId = '';
  });

  bus.on('nav:agent-selected', ({ agentId, workgroupId }) => {
    const s = store.get();
    const tree = s.data.treeData[workgroupId];
    const agent = (tree?.agents || []).find(a => a.id === agentId);
    if (!agent) return;

    _currentAgentId = agentId;
    _currentWorkgroupId = workgroupId;

    // Clear active conversation so store-driven view toggle doesn't fight us
    store.update(st => { st.nav.activeConversationId = ''; });
    store.notify('nav.activeConversationId');

    renderProfile(agent);
    showAgentProfile();
  });

}
