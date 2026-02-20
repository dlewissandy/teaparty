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
  if (profileView) profileView.classList.remove('hidden');
  if (chatView) chatView.classList.add('hidden');
  if (homeView) homeView.classList.add('hidden');
}

function renderProfile(agent) {
  const avatarEl = document.getElementById('agent-profile-avatar');
  const nameEl = document.getElementById('agent-profile-name');
  const roleEl = document.getElementById('agent-profile-role');
  const bodyEl = document.getElementById('agent-profile-body');

  if (avatarEl) avatarEl.innerHTML = generateBotSvg(agent.name);
  if (nameEl) nameEl.textContent = agent.name;
  if (roleEl) roleEl.textContent = agent.role || '';

  if (!bodyEl) return;

  let html = '';

  if (agent.description) {
    html += `
      <section class="agent-profile-section">
        <h4 class="agent-profile-section-title">Description</h4>
        <p class="agent-profile-text">${escapeHtml(agent.description)}</p>
      </section>`;
  }

  if (agent.personality) {
    html += `
      <section class="agent-profile-section">
        <h4 class="agent-profile-section-title">Personality</h4>
        <p class="agent-profile-text">${escapeHtml(agent.personality)}</p>
      </section>`;
  }

  if (agent.backstory) {
    html += `
      <section class="agent-profile-section">
        <h4 class="agent-profile-section-title">Backstory</h4>
        <p class="agent-profile-text">${escapeHtml(agent.backstory)}</p>
      </section>`;
  }

  // Model & Behavior
  const modelParts = [];
  if (agent.model) modelParts.push(`<span class="agent-profile-kv"><span class="agent-profile-key">Model</span> ${escapeHtml(agent.model)}</span>`);
  if (agent.temperature != null) modelParts.push(`<span class="agent-profile-kv"><span class="agent-profile-key">Temperature</span> ${agent.temperature}</span>`);
  if (agent.verbosity) modelParts.push(`<span class="agent-profile-kv"><span class="agent-profile-key">Verbosity</span> ${escapeHtml(agent.verbosity)}</span>`);
  if (agent.response_threshold != null) modelParts.push(`<span class="agent-profile-kv"><span class="agent-profile-key">Response threshold</span> ${agent.response_threshold}</span>`);

  if (modelParts.length) {
    html += `
      <section class="agent-profile-section">
        <h4 class="agent-profile-section-title">Model & Behavior</h4>
        <div class="agent-profile-kvs">${modelParts.join('')}</div>
      </section>`;
  }

  // Tools
  const tools = agent.tool_names || [];
  if (tools.length) {
    const chips = tools.map(t => `<span class="tool-chip">${escapeHtml(t)}</span>`).join('');
    html += `
      <section class="agent-profile-section">
        <h4 class="agent-profile-section-title">Tools</h4>
        <div class="tool-chip-list">${chips}</div>
      </section>`;
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
