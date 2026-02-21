// Agent profile view: displays agent details in the main content area.
// Listens for nav:agent-selected, renders a read-only profile with a Chat button.

import { bus } from '../../core/bus.js';
import { escapeHtml } from '../../core/utils.js';
import { generateBotSvg } from '../../components/shared/avatar.js';
import { openAgentConversation } from '../data/data-loading.js';

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

function renderProfile(agent) {
  const avatarEl = document.getElementById('agent-profile-avatar');
  const nameEl = document.getElementById('agent-profile-name');
  const subtitleEl = document.getElementById('agent-profile-role');
  const bodyEl = document.getElementById('agent-profile-body');

  if (avatarEl) avatarEl.innerHTML = generateBotSvg(agent.name);
  if (nameEl) nameEl.textContent = agent.name;
  if (subtitleEl) subtitleEl.textContent = agent.description || '';

  if (!bodyEl) return;

  let html = '';

  if (agent.prompt) {
    html += `
      <div class="agent-profile-card">
        <h4 class="agent-profile-card-title">Prompt</h4>
        <p class="agent-profile-text">${escapeHtml(agent.prompt)}</p>
      </div>`;
  }

  // Configuration
  const configParts = [];
  if (agent.model) configParts.push(`<span class="agent-profile-kv"><span class="agent-profile-key">Model</span> ${escapeHtml(agent.model)}</span>`);
  if (agent.permission_mode && agent.permission_mode !== 'default') configParts.push(`<span class="agent-profile-kv"><span class="agent-profile-key">Permissions</span> ${escapeHtml(agent.permission_mode)}</span>`);
  if (agent.memory) configParts.push(`<span class="agent-profile-kv"><span class="agent-profile-key">Memory</span> ${escapeHtml(agent.memory)}</span>`);
  if (agent.background) configParts.push(`<span class="agent-profile-kv"><span class="agent-profile-key">Background</span> yes</span>`);
  if (agent.isolation === false) configParts.push(`<span class="agent-profile-kv"><span class="agent-profile-key">Isolation</span> off</span>`);

  if (configParts.length) {
    html += `
      <div class="agent-profile-card">
        <h4 class="agent-profile-card-title">Configuration</h4>
        <div class="agent-profile-kvs">${configParts.join('')}</div>
      </div>`;
  }

  // Tools
  const tools = agent.tools || [];
  if (tools.length) {
    const chips = tools.map(t => `<span class="tool-chip">${escapeHtml(t)}</span>`).join('');
    html += `
      <div class="agent-profile-card">
        <h4 class="agent-profile-card-title">Tools</h4>
        <div class="tool-chip-list">${chips}</div>
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

  const chatBtn = document.getElementById('agent-profile-chat-btn');
  if (chatBtn) {
    chatBtn.addEventListener('click', async () => {
      if (!_currentAgentId || !_currentWorkgroupId) return;
      chatBtn.disabled = true;
      try {
        await openAgentConversation(_currentWorkgroupId, _currentAgentId);
      } finally {
        chatBtn.disabled = false;
      }
    });
  }
}
