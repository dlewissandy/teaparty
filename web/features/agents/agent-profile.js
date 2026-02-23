// Agent profile view: displays agent details in the main content area.
// Listens for nav:agent-selected, renders a read-only profile.

import { bus } from '../../core/bus.js';
import { escapeHtml } from '../../core/utils.js';
import { generateBotSvg, avatarColor, initialsFromName } from '../../components/shared/avatar.js';
import { api } from '../../core/api.js';
import { flash } from '../../components/shared/flash.js';

let _store = null;
let _currentAgentId = '';
let _currentWorkgroupId = '';

function _dismissPopover() {
  document.getElementById('ap-tool-popover')?.remove();
}

function showAgentProfile() {
  const views = ['chat-view', 'home-view', 'partner-profile-view', 'workgroup-profile-view', 'directory-view', 'org-dashboard-view', 'org-settings-view', 'create-project-form'];
  for (const id of views) { document.getElementById(id)?.classList.add('hidden'); }
  document.getElementById('agent-profile-view')?.classList.remove('hidden');

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
  workgroups: '<svg viewBox="0 0 20 20" fill="none" width="18" height="18"><path d="M3 5a2 2 0 012-2h3l2 2h5a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V5z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/></svg>',
};

function cardHeader(title, iconKey) {
  return `<div class="agent-profile-card-header"><span class="agent-profile-card-icon">${CARD_ICONS[iconKey] || ''}</span><h4 class="agent-profile-card-title">${escapeHtml(title)}</h4></div>`;
}

/** Human-friendly labels for select-style values. */
const MODEL_LABELS = { sonnet: 'Sonnet', opus: 'Opus', haiku: 'Haiku' };
const PERM_LABELS = { default: 'Default', acceptEdits: 'Accept Edits', dontAsk: "Don't Ask", plan: 'Plan' };

/** Resolve the workgroup ID to use for PATCH calls. */
function _agentWorkgroupId(agent) {
  return _currentWorkgroupId || (agent.workgroup_ids || [])[0] || '';
}

/** Remove a tool from the agent (direct DOM removal, like workgroup pills). */
async function _removeTool(agent, toolName) {
  const chip = document.querySelector(`.tool-chip[data-tool="${CSS.escape(toolName)}"]`);
  if (chip) chip.classList.add('tool-chip--removing');

  const wgId = _agentWorkgroupId(agent);
  if (!wgId) return;

  try {
    const newTools = (agent.tools || []).filter(t => t !== toolName);
    await api(`/api/workgroups/${wgId}/agents/${agent.id}`, {
      method: 'PATCH',
      body: { tools: newTools },
    });
    agent.tools = newTools;
    if (chip) chip.remove();
    flash(`Removed ${toolName}`, 'success');
  } catch (err) {
    if (chip) chip.classList.remove('tool-chip--removing');
    flash(err.message || 'Failed to remove tool', 'error');
  }
}

/** Create a tool chip DOM element with its remove handler wired up. */
function _makeToolChip(agent, toolName) {
  const chip = document.createElement('span');
  chip.className = 'tool-chip';
  chip.dataset.tool = toolName;
  chip.innerHTML = `${escapeHtml(toolName)}<button type="button" class="tool-chip-remove" title="Remove ${escapeHtml(toolName)}" aria-label="Remove ${escapeHtml(toolName)}"><svg viewBox="0 0 10 10"><path d="M2 2l6 6M8 2l-6 6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg></button>`;
  chip.querySelector('.tool-chip-remove').addEventListener('click', () => _removeTool(agent, toolName));
  return chip;
}

/** Fetch toolsets and show the add-toolset popover. */
async function _showAddToolPopover(agent, anchorBtn) {
  // Close any existing popover
  document.getElementById('ap-tool-popover')?.remove();

  const wgId = _agentWorkgroupId(agent);
  if (!wgId) return;

  let toolsets;
  try {
    toolsets = await api(`/api/workgroups/${wgId}/toolsets`);
  } catch {
    flash('Failed to load toolsets', 'error');
    return;
  }

  const currentTools = new Set(agent.tools || []);

  // Filter to toolsets that have at least one tool not yet added
  const available = toolsets.filter(ts =>
    ts.tools.some(t => !currentTools.has(t))
  );

  if (!available.length) {
    flash('All available tools are already added', 'info');
    return;
  }

  // Build popover
  const popover = document.createElement('div');
  popover.id = 'ap-tool-popover';
  popover.className = 'ap-tool-popover';

  const header = document.createElement('div');
  header.className = 'ap-tool-popover-header';
  header.textContent = 'Add toolset';
  popover.appendChild(header);

  const list = document.createElement('div');
  list.className = 'ap-tool-popover-list';

  for (const ts of available) {
    const missing = ts.tools.filter(t => !currentTools.has(t));
    const row = document.createElement('button');
    row.type = 'button';
    row.className = 'ap-tool-popover-item';
    row.innerHTML = `
      <span class="ap-tool-popover-name">${escapeHtml(ts.name)}</span>
      <span class="ap-tool-popover-desc">${escapeHtml(ts.description)}</span>
      <span class="ap-tool-popover-tools">${missing.map(t => `<span class="ap-tool-popover-tool-tag">+ ${escapeHtml(t)}</span>`).join('')}</span>`;
    row.addEventListener('click', async () => {
      row.disabled = true;
      row.classList.add('ap-tool-popover-item--adding');
      try {
        const newTools = [...(agent.tools || []), ...missing];
        await api(`/api/workgroups/${wgId}/agents/${agent.id}`, {
          method: 'PATCH',
          body: { tools: newTools },
        });
        agent.tools = newTools;
        // Insert new chips before the add button
        const chipList = document.getElementById('ap-tool-chips');
        if (chipList) {
          for (const toolName of missing) {
            chipList.insertBefore(_makeToolChip(agent, toolName), anchorBtn);
          }
        }
        flash(`Added ${ts.name}`, 'success');
        popover.remove();
      } catch (err) {
        row.disabled = false;
        row.classList.remove('ap-tool-popover-item--adding');
        flash(err.message || 'Failed to add toolset', 'error');
      }
    });
    list.appendChild(row);
  }
  popover.appendChild(list);

  // Position relative to the anchor button
  const rect = anchorBtn.getBoundingClientRect();
  popover.style.position = 'fixed';
  popover.style.top = `${rect.bottom + 6}px`;
  popover.style.left = `${rect.left}px`;
  document.body.appendChild(popover);

  // Reposition if it overflows
  requestAnimationFrame(() => {
    const pr = popover.getBoundingClientRect();
    if (pr.right > window.innerWidth - 12) {
      popover.style.left = `${window.innerWidth - pr.width - 12}px`;
    }
    if (pr.bottom > window.innerHeight - 12) {
      popover.style.top = `${rect.top - pr.height - 6}px`;
    }
  });

  // Dismiss on outside click
  function dismiss(e) {
    if (!popover.contains(e.target) && e.target !== anchorBtn) {
      popover.remove();
      document.removeEventListener('pointerdown', dismiss, true);
    }
  }
  requestAnimationFrame(() => {
    document.addEventListener('pointerdown', dismiss, true);
  });
}

function wireProfileEvents(agent) {
  const bodyEl = document.getElementById('agent-profile-body');
  if (!bodyEl) return;

  // Remove tool (chips rendered from innerHTML)
  bodyEl.querySelectorAll('.tool-chip-remove[data-tool]').forEach(btn => {
    btn.addEventListener('click', () => _removeTool(agent, btn.dataset.tool));
  });

  // Add tool button
  const addBtn = document.getElementById('ap-tool-add-btn');
  if (addBtn) {
    addBtn.addEventListener('click', () => _showAddToolPopover(agent, addBtn));
  }

  // View workgroup
  bodyEl.querySelectorAll('[data-action="view-workgroup"]').forEach(btn => {
    btn.addEventListener('click', () => {
      const workgroupId = btn.dataset.workgroupId;
      if (_store) {
        _store.update(s => { s.nav.sidebarSelection = `workgroup:${workgroupId}`; });
      }
      bus.emit('nav:workgroup-profile', { workgroupId });
    });
  });

  // Remove from workgroup
  bodyEl.querySelectorAll('[data-action="remove-from-workgroup"]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const workgroupId = btn.dataset.workgroupId;
      const pill = btn.closest('.ap-wg-pill');
      if (pill) pill.classList.add('ap-wg-pill--removing');
      try {
        await api(`/api/agents/${agent.id}/workgroups/${workgroupId}`, { method: 'DELETE' });
        if (pill) pill.remove();
        flash('Removed from workgroup', 'success');
        bus.emit('data:refresh');
      } catch (err) {
        if (pill) pill.classList.remove('ap-wg-pill--removing');
        flash(err.message || 'Failed to remove', 'error');
      }
    });
  });

  // Dropzone for workgroups
  const dropzone = document.getElementById('ap-wg-dropzone');
  if (dropzone) {
    dropzone.addEventListener('dragover', (e) => {
      if (!e.dataTransfer.types.includes('application/x-teaparty-workgroup')) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'copy';
      dropzone.classList.add('ap-wg-dropzone--over');
    });
    dropzone.addEventListener('dragleave', (e) => {
      if (!dropzone.contains(e.relatedTarget)) {
        dropzone.classList.remove('ap-wg-dropzone--over');
      }
    });
    dropzone.addEventListener('drop', async (e) => {
      e.preventDefault();
      dropzone.classList.remove('ap-wg-dropzone--over');
      const raw = e.dataTransfer.getData('application/x-teaparty-workgroup');
      if (!raw) return;
      let data;
      try { data = JSON.parse(raw); } catch { return; }

      // Check if already in this workgroup
      const agentWgIds = agent.workgroup_ids || [];
      if (agentWgIds.includes(data.workgroupId)) {
        flash('Agent is already in this workgroup', 'info');
        return;
      }

      dropzone.classList.add('ap-wg-dropzone--loading');
      try {
        await api(`/api/agents/${agent.id}/workgroups/${data.workgroupId}`, { method: 'POST' });
        flash('Added to workgroup', 'success');
        bus.emit('data:refresh');
      } catch (err) {
        flash(err.message || 'Failed to add to workgroup', 'error');
      }
      dropzone.classList.remove('ap-wg-dropzone--loading');
    });
  }
}

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

  // Workgroups
  const s = _store.get();
  const allWorkgroups = s.data.workgroups || [];
  const org = (s.data.organizations || []).find(o => o.id === agent.organization_id);
  const isOwner = org?.owner_id === s.auth.user?.id;
  const agentWgIds = agent.workgroup_ids || [];
  const agentWorkgroups = agentWgIds
    .map(wid => allWorkgroups.find(w => w.id === wid))
    .filter(Boolean);

  let wgPillsHtml = '<div class="ap-wg-pills">';
  for (const wg of agentWorkgroups) {
    const color = avatarColor(wg.name);
    const initials = initialsFromName(wg.name);
    const removable = isOwner && !agent.is_lead;
    wgPillsHtml += `
      <span class="ap-wg-pill" data-workgroup-id="${escapeHtml(wg.id)}">
        <span class="ap-wg-pill-avatar" style="background:${escapeHtml(color)}">${escapeHtml(initials)}</span>
        <button type="button" class="ap-wg-pill-name" data-action="view-workgroup" data-workgroup-id="${escapeHtml(wg.id)}">${escapeHtml(wg.name)}</button>${removable ? `<button type="button" class="ap-wg-pill-x" data-action="remove-from-workgroup" data-workgroup-id="${escapeHtml(wg.id)}" title="Remove from workgroup" aria-label="Remove from ${escapeHtml(wg.name)}">&times;</button>` : ''}
      </span>`;
  }
  if (!agentWorkgroups.length) {
    wgPillsHtml += '<span class="ap-wg-pills-empty">Not assigned to any workgroup</span>';
  }
  wgPillsHtml += '</div>';

  let dropzoneHtml = '';
  if (isOwner) {
    dropzoneHtml = `
      <div class="ap-wg-dropzone" id="ap-wg-dropzone">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M8 3v10M3 8h10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
        <span>Drag a workgroup here from the sidebar</span>
      </div>`;
  }

  html += `
    <div class="agent-profile-card">
      ${cardHeader('Workgroups', 'workgroups')}
      <div class="agent-profile-card-body" style="padding:0">
        ${wgPillsHtml}
        ${dropzoneHtml}
      </div>
    </div>`;

  // Tools
  const tools = agent.tools || [];
  let toolsBody = '<div class="tool-chip-list" id="ap-tool-chips">';
  for (const t of tools) {
    toolsBody += `<span class="tool-chip" data-tool="${escapeHtml(t)}">${escapeHtml(t)}<button type="button" class="tool-chip-remove" data-action="remove-tool" data-tool="${escapeHtml(t)}" title="Remove ${escapeHtml(t)}" aria-label="Remove ${escapeHtml(t)}"><svg viewBox="0 0 10 10"><path d="M2 2l6 6M8 2l-6 6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg></button></span>`;
  }
  toolsBody += `<button type="button" class="ap-tool-add-btn" id="ap-tool-add-btn" title="Add tool" aria-label="Add tool"><svg viewBox="0 0 16 16" fill="none" width="14" height="14"><path d="M8 3v10M3 8h10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg></button>`;
  toolsBody += '</div>';
  html += `
    <div class="agent-profile-card">
      ${cardHeader('Tools', 'tools')}
      <div class="agent-profile-card-body">
        ${toolsBody}
      </div>
    </div>`;

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
  wireProfileEvents(agent);
}

/** Look up an agent by ID from store data (tree data then unassigned). */
function _findAgent(store, agentId, workgroupId) {
  const s = store.get();
  let agent = null;
  if (workgroupId) {
    const tree = s.data.treeData[workgroupId];
    agent = (tree?.agents || []).find(a => a.id === agentId) || null;
  }
  if (!agent) {
    for (const agents of Object.values(s.data.unassignedAgents || {})) {
      agent = agents.find(a => a.id === agentId) || null;
      if (agent) break;
    }
  }
  if (!agent) {
    for (const tree of Object.values(s.data.treeData || {})) {
      agent = (tree?.agents || []).find(a => a.id === agentId) || null;
      if (agent) break;
    }
  }
  return agent;
}

export function initAgentProfile(store) {
  _store = store;

  // Hide profile when navigating away to an org or home
  bus.on('nav:org-selected', () => {
    _dismissPopover();
    const profileView = document.getElementById('agent-profile-view');
    if (profileView) profileView.classList.add('hidden');
    _currentAgentId = '';
    _currentWorkgroupId = '';
  });

  bus.on('nav:home', () => {
    _dismissPopover();
    const profileView = document.getElementById('agent-profile-view');
    if (profileView) profileView.classList.add('hidden');
    _currentAgentId = '';
    _currentWorkgroupId = '';
  });

  bus.on('nav:agent-selected', ({ agentId, workgroupId }) => {
    const agent = _findAgent(store, agentId, workgroupId);
    if (!agent) return;

    _currentAgentId = agentId;
    _currentWorkgroupId = workgroupId;

    // Clear active conversation so store-driven view toggle doesn't fight us
    store.update(st => { st.nav.activeConversationId = ''; });
    store.notify('nav.activeConversationId');

    renderProfile(agent);
    showAgentProfile();
  });

  // Re-render profile when underlying data changes (e.g. workgroup add/remove)
  function refreshIfVisible() {
    if (!_currentAgentId) return;
    const agent = _findAgent(store, _currentAgentId, _currentWorkgroupId);
    if (!agent) return;
    renderProfile(agent);
  }
  store.on('data.treeData', refreshIfVisible);
  store.on('data.unassignedAgents', refreshIfVisible);
}
