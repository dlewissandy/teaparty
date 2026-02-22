// Workgroup configuration view: inline form for configuring a Claude multiagent team.
// Renders inside #workgroup-profile-view in main-content, following the org-cfg design system.

import { bus } from '../../core/bus.js';
import { api } from '../../core/api.js';
import { escapeHtml, jobDisplayName } from '../../core/utils.js';
import { flash } from '../../components/shared/flash.js';
import { avatarColor, initialsFromName, generateBotSvg } from '../../components/shared/avatar.js';

let _store = null;
let _currentWorkgroupId = '';
let _lastRenderFingerprint = '';

const MODEL_OPTIONS = [
  { value: 'sonnet', label: 'Sonnet' },
  { value: 'haiku', label: 'Haiku' },
  { value: 'opus', label: 'Opus' },
];

const PERMISSION_OPTIONS = [
  { value: 'acceptEdits', label: 'Accept Edits' },
  { value: 'plan', label: 'Plan (approval required)' },
  { value: 'bypassPermissions', label: 'Bypass Permissions' },
];

function showView() {
  const views = [
    'chat-view', 'home-view', 'agent-profile-view', 'partner-profile-view',
    'directory-view', 'org-dashboard-view', 'org-settings-view', 'create-project-form',
  ];
  for (const id of views) { document.getElementById(id)?.classList.add('hidden'); }
  document.getElementById('workgroup-profile-view')?.classList.remove('hidden');
}

function hideView() {
  document.getElementById('workgroup-profile-view')?.classList.add('hidden');
  _currentWorkgroupId = '';
  _lastRenderFingerprint = '';
}

export function initWorkgroupProfile(store) {
  _store = store;

  bus.on('nav:workgroup-profile', ({ workgroupId }) => {
    _currentWorkgroupId = workgroupId;
    store.update(s => { s.nav.activeConversationId = ''; });
    store.notify('nav.activeConversationId');
    showView();
    render(workgroupId);
  });

  bus.on('nav:org-selected', () => hideView());
  bus.on('nav:home', () => hideView());

  // Re-render when data changes (agents may have moved)
  store.on('data.treeData', () => {
    if (!_currentWorkgroupId) return;
    const fp = _fingerprint(_currentWorkgroupId);
    if (fp === _lastRenderFingerprint) return;
    render(_currentWorkgroupId);
  });

  // Delegated click handlers — survive re-renders
  const root = document.getElementById('workgroup-profile-content');
  if (root) {
    root.addEventListener('click', (e) => {
      const viewBtn = e.target.closest('[data-action="view-agent"]');
      if (viewBtn) {
        store.update(s => { s.nav.sidebarSelection = `agent:${viewBtn.dataset.agentId}`; });
        bus.emit('nav:agent-selected', {
          agentId: viewBtn.dataset.agentId,
          workgroupId: viewBtn.dataset.workgroupId,
        });
        return;
      }

      const removeBtn = e.target.closest('[data-action="remove-agent"]');
      if (removeBtn) {
        _handleRemoveAgent(removeBtn);
        return;
      }

      const jobBtn = e.target.closest('[data-action="open-job"]');
      if (jobBtn) {
        store.update(s => { s.nav.sidebarSelection = `job:${jobBtn.dataset.conversationId}`; });
        bus.emit('nav:conversation-selected', {
          workgroupId: _currentWorkgroupId,
          conversationId: jobBtn.dataset.conversationId,
        });
      }
    });
  }
}

async function _handleRemoveAgent(btn) {
  const agentId = btn.dataset.agentId;
  const pill = btn.closest('.wg-agent-pill');

  if (pill) { pill.classList.add('wg-agent-pill--removing'); }
  try {
    await api(`/api/workgroups/${_currentWorkgroupId}/agents/${agentId}`, {
      method: 'DELETE',
    });
    if (pill) pill.remove();
    flash('Agent removed', 'success');
    bus.emit('data:refresh');
  } catch (err) {
    if (pill) { pill.classList.remove('wg-agent-pill--removing'); }
    flash(err.message || 'Failed to remove agent', 'error');
  }
}

function _fingerprint(workgroupId) {
  const s = _store.get();
  const wg = (s.data.workgroups || []).find(w => w.id === workgroupId);
  if (!wg) return '';
  const tree = s.data.treeData[workgroupId];
  const agentIds = (tree?.agents || []).map(a => `${a.id}:${a.name}:${a.is_lead}`).join(',');
  const jobIds = (tree?.jobs || []).map(j => j.id).join(',');
  return `${wg.team_model}|${wg.team_permission_mode}|${wg.team_max_turns}|${wg.team_max_cost_usd}|${wg.team_max_time_seconds}|${wg.workspace_enabled}|${agentIds}|${jobIds}`;
}

function selectOptions(options, currentValue) {
  return options.map(o =>
    `<option value="${o.value}"${o.value === currentValue ? ' selected' : ''}>${escapeHtml(o.label)}</option>`
  ).join('');
}

function render(workgroupId) {
  const s = _store.get();
  const wg = (s.data.workgroups || []).find(w => w.id === workgroupId);
  if (!wg) return;

  const container = document.getElementById('workgroup-profile-content');
  if (!container) return;

  const org = (s.data.organizations || []).find(o => o.id === wg.organization_id);
  const isOwner = org?.owner_id === s.auth.user?.id;
  const tree = s.data.treeData[workgroupId];
  const agents = tree?.agents || [];
  const jobs = tree?.jobs || [];
  const color = avatarColor(wg.name);
  const initials = initialsFromName(wg.name);

  const model = wg.team_model || 'sonnet';
  const permMode = wg.team_permission_mode || 'acceptEdits';
  const maxTurns = wg.team_max_turns ?? 30;
  const maxCost = wg.team_max_cost_usd ?? '';
  const maxTime = wg.team_max_time_seconds ?? '';
  const workspaceEnabled = wg.workspace_enabled !== false;

  // Build agent roster HTML — pill layout with drag-and-drop
  let agentRosterHtml = '<div class="wg-agent-pills" id="wg-agent-pills">';
  for (const agent of agents) {
    const svg = generateBotSvg(agent.name);
    const removable = isOwner && !agent.is_lead;
    agentRosterHtml += `
      <span class="wg-agent-pill${agent.is_lead ? ' wg-agent-pill--lead' : ''}" data-agent-id="${escapeHtml(agent.id)}" data-workgroup-id="${escapeHtml(workgroupId)}">
        <span class="wg-agent-pill-avatar">${svg}</span>
        <button type="button" class="wg-agent-pill-name" data-action="view-agent" data-agent-id="${escapeHtml(agent.id)}" data-workgroup-id="${escapeHtml(workgroupId)}">${escapeHtml(agent.name)}</button>${removable ? `<button type="button" class="wg-agent-pill-x" data-action="remove-agent" data-agent-id="${escapeHtml(agent.id)}" title="Remove from team" aria-label="Remove ${escapeHtml(agent.name)}">&times;</button>` : ''}
      </span>`;
  }
  if (!agents.length) {
    agentRosterHtml += '<span class="wg-agent-pills-empty">No agents yet</span>';
  }
  agentRosterHtml += '</div>';

  if (isOwner) {
    agentRosterHtml += `
      <div class="wg-agent-dropzone" id="wg-agent-dropzone">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M8 3v10M3 8h10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
        <span>Drag an agent here from the sidebar</span>
      </div>`;
  }

  // Build jobs HTML
  let jobsHtml = '';
  if (jobs.length) {
    jobsHtml = `
      <div class="org-cfg-card">
        <div class="org-cfg-card-header">
          <svg class="org-cfg-card-icon" viewBox="0 0 20 20" fill="none" width="20" height="20"><path d="M4 4h12a1 1 0 011 1v10a1 1 0 01-1 1H4a1 1 0 01-1-1V5a1 1 0 011-1z" stroke="currentColor" stroke-width="1.3"/><path d="M7 8h6M7 11h4" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>
          <h4 class="org-cfg-card-title">Conversations</h4>
        </div>
        <div class="wg-job-list">`;
    for (const job of jobs) {
      const name = jobDisplayName(job);
      jobsHtml += `
          <button type="button" class="wg-job-link" data-action="open-job" data-conversation-id="${escapeHtml(job.id)}">
            <span class="wg-job-hash">#</span>
            <span>${escapeHtml(name)}</span>
          </button>`;
    }
    jobsHtml += `
        </div>
      </div>`;
  }

  // Owner gets an editable form; non-owners see read-only
  if (isOwner) {
    container.innerHTML = `
      <form id="wg-config-form" class="org-cfg">

        <div class="org-cfg-hero">
          <span class="org-cfg-avatar-initials" style="background:${escapeHtml(color)}">${escapeHtml(initials)}</span>
          <div class="org-cfg-hero-text">
            <h3 class="org-cfg-name">${escapeHtml(wg.name)}</h3>
            <p class="org-cfg-meta">Agent Team Configuration</p>
          </div>
        </div>

        <!-- Team Model -->
        <div class="org-cfg-card">
          <div class="org-cfg-card-header">
            <svg class="org-cfg-card-icon" viewBox="0 0 20 20" fill="none" width="20" height="20"><circle cx="10" cy="10" r="2" fill="currentColor"/><path d="M10 2v2M10 16v2M2 10h2M16 10h2M4.22 4.22l1.42 1.42M14.36 14.36l1.42 1.42M4.22 15.78l1.42-1.42M14.36 5.64l1.42-1.42" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>
            <h4 class="org-cfg-card-title">Model &amp; Permissions</h4>
          </div>

          <div class="org-cfg-billing-grid">
            <label class="org-cfg-field">
              <span class="org-cfg-label">Model</span>
              <select name="team_model">${selectOptions(MODEL_OPTIONS, model)}</select>
            </label>
            <label class="org-cfg-field">
              <span class="org-cfg-label">Permission Mode</span>
              <select name="team_permission_mode">${selectOptions(PERMISSION_OPTIONS, permMode)}</select>
            </label>
          </div>
        </div>

        <!-- Limits -->
        <div class="org-cfg-card">
          <div class="org-cfg-card-header">
            <svg class="org-cfg-card-icon" viewBox="0 0 20 20" fill="none" width="20" height="20"><path d="M10 3v7l4 4" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/><circle cx="10" cy="10" r="7.5" stroke="currentColor" stroke-width="1.3"/></svg>
            <h4 class="org-cfg-card-title">Limits</h4>
          </div>
          <p class="org-cfg-card-desc">Safety limits for agent team sessions.</p>

          <div class="org-cfg-billing-grid" style="grid-template-columns: 1fr 1fr 1fr">
            <label class="org-cfg-field">
              <span class="org-cfg-label">Max Turns</span>
              <div class="org-cfg-input-with-unit">
                <input type="number" name="team_max_turns" value="${maxTurns}" min="1" max="500" />
                <span class="org-cfg-input-unit">turns</span>
              </div>
            </label>
            <label class="org-cfg-field">
              <span class="org-cfg-label">Max Cost</span>
              <div class="org-cfg-input-with-unit">
                <input type="number" name="team_max_cost_usd" value="${escapeHtml(String(maxCost))}" min="0" step="0.01" placeholder="No limit" />
                <span class="org-cfg-input-unit">USD</span>
              </div>
            </label>
            <label class="org-cfg-field">
              <span class="org-cfg-label">Max Time</span>
              <div class="org-cfg-input-with-unit">
                <input type="number" name="team_max_time_seconds" value="${escapeHtml(String(maxTime))}" min="0" step="1" placeholder="No limit" />
                <span class="org-cfg-input-unit">sec</span>
              </div>
            </label>
          </div>
        </div>

        <!-- Workspace -->
        <div class="org-cfg-card">
          <div class="org-cfg-card-header">
            <svg class="org-cfg-card-icon" viewBox="0 0 20 20" fill="none" width="20" height="20"><path d="M3 5a2 2 0 012-2h3l2 2h5a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V5z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/></svg>
            <h4 class="org-cfg-card-title">Workspace</h4>
          </div>

          <div class="org-cfg-toggle-row">
            <div>
              <span class="org-cfg-toggle-label">Shared file workspace</span>
              <span class="org-cfg-toggle-hint">Agents in this team share a file workspace for collaboration</span>
            </div>
            <label class="org-cfg-toggle">
              <input type="checkbox" name="workspace_enabled" ${workspaceEnabled ? 'checked' : ''} />
              <span class="org-cfg-toggle-track"></span>
              <span class="org-cfg-toggle-thumb"></span>
            </label>
          </div>
        </div>

        <!-- Agents -->
        <div class="org-cfg-card">
          <div class="org-cfg-card-header">
            <svg class="org-cfg-card-icon" viewBox="0 0 20 20" fill="none" width="20" height="20"><rect x="4" y="5" width="12" height="11" rx="3" stroke="currentColor" stroke-width="1.4"/><circle cx="8" cy="10" r="1.2" fill="currentColor"/><circle cx="12" cy="10" r="1.2" fill="currentColor"/><path d="M8.5 13.5q1.5 1 3 0" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/><line x1="10" y1="5" x2="10" y2="2.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/><circle cx="10" cy="2" r="1" fill="currentColor"/></svg>
            <h4 class="org-cfg-card-title">Agents</h4>
          </div>
          ${agentRosterHtml}
        </div>

        ${jobsHtml}

        <!-- Actions -->
        <div class="org-cfg-actions">
          <button type="button" class="btn btn-ghost" id="wg-config-cancel">Cancel</button>
          <button type="submit" class="btn btn-primary" id="wg-config-save">Save Changes</button>
        </div>
      </form>
    `;
  } else {
    // Read-only view for non-owners
    const modelLabel = MODEL_OPTIONS.find(o => o.value === model)?.label || model;
    const permLabel = PERMISSION_OPTIONS.find(o => o.value === permMode)?.label || permMode;

    container.innerHTML = `
      <div class="org-cfg">

        <div class="org-cfg-hero">
          <span class="org-cfg-avatar-initials" style="background:${escapeHtml(color)}">${escapeHtml(initials)}</span>
          <div class="org-cfg-hero-text">
            <h3 class="org-cfg-name">${escapeHtml(wg.name)}</h3>
            <p class="org-cfg-meta">Agent Team</p>
          </div>
        </div>

        <div class="org-cfg-card">
          <div class="org-cfg-card-header">
            <svg class="org-cfg-card-icon" viewBox="0 0 20 20" fill="none" width="20" height="20"><circle cx="10" cy="10" r="2" fill="currentColor"/><path d="M10 2v2M10 16v2M2 10h2M16 10h2M4.22 4.22l1.42 1.42M14.36 14.36l1.42 1.42M4.22 15.78l1.42-1.42M14.36 5.64l1.42-1.42" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>
            <h4 class="org-cfg-card-title">Configuration</h4>
          </div>
          <div class="wg-readonly-grid">
            <span class="wg-readonly-kv"><span class="wg-readonly-key">Model</span>${escapeHtml(modelLabel)}</span>
            <span class="wg-readonly-kv"><span class="wg-readonly-key">Permissions</span>${escapeHtml(permLabel)}</span>
            <span class="wg-readonly-kv"><span class="wg-readonly-key">Max Turns</span>${maxTurns}</span>
            ${maxCost ? `<span class="wg-readonly-kv"><span class="wg-readonly-key">Max Cost</span>$${escapeHtml(String(maxCost))}</span>` : ''}
            ${maxTime ? `<span class="wg-readonly-kv"><span class="wg-readonly-key">Max Time</span>${escapeHtml(String(maxTime))}s</span>` : ''}
            <span class="wg-readonly-kv"><span class="wg-readonly-key">Workspace</span>${workspaceEnabled ? 'Enabled' : 'Disabled'}</span>
          </div>
        </div>

        <div class="org-cfg-card">
          <div class="org-cfg-card-header">
            <svg class="org-cfg-card-icon" viewBox="0 0 20 20" fill="none" width="20" height="20"><rect x="4" y="5" width="12" height="11" rx="3" stroke="currentColor" stroke-width="1.4"/><circle cx="8" cy="10" r="1.2" fill="currentColor"/><circle cx="12" cy="10" r="1.2" fill="currentColor"/><path d="M8.5 13.5q1.5 1 3 0" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/><line x1="10" y1="5" x2="10" y2="2.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/><circle cx="10" cy="2" r="1" fill="currentColor"/></svg>
            <h4 class="org-cfg-card-title">Agents</h4>
          </div>
          <div class="wg-agent-pills" style="padding:12px 22px">
            ${agents.map(agent => {
              const svg = generateBotSvg(agent.name);
              return `<span class="wg-agent-pill${agent.is_lead ? ' wg-agent-pill--lead' : ''}" data-agent-id="${escapeHtml(agent.id)}" data-workgroup-id="${escapeHtml(workgroupId)}">
                <span class="wg-agent-pill-avatar">${svg}</span>
                <button type="button" class="wg-agent-pill-name" data-action="view-agent" data-agent-id="${escapeHtml(agent.id)}" data-workgroup-id="${escapeHtml(workgroupId)}">${escapeHtml(agent.name)}</button>
              </span>`;
            }).join('')}
            ${!agents.length ? '<span class="wg-agent-pills-empty">No agents</span>' : ''}
          </div>
        </div>

        ${jobsHtml}
      </div>
    `;
  }

  _lastRenderFingerprint = _fingerprint(workgroupId);
  wireEvents(workgroupId);
}

function wireEvents(workgroupId) {
  const root = document.getElementById('workgroup-profile-content');

  // Config form save
  const form = document.getElementById('wg-config-form');
  form?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = document.getElementById('wg-config-save');
    if (btn) { btn.disabled = true; btn.textContent = 'Saving...'; }

    const fd = new FormData(form);
    const body = {
      team_model: fd.get('team_model'),
      team_permission_mode: fd.get('team_permission_mode'),
      team_max_turns: parseInt(fd.get('team_max_turns'), 10) || 30,
      workspace_enabled: fd.has('workspace_enabled'),
    };
    const costVal = fd.get('team_max_cost_usd');
    body.team_max_cost_usd = costVal ? parseFloat(costVal) : null;
    const timeVal = fd.get('team_max_time_seconds');
    body.team_max_time_seconds = timeVal ? parseInt(timeVal, 10) : null;

    try {
      await api(`/api/workgroups/${workgroupId}`, { method: 'PATCH', body });
      flash('Configuration saved', 'success');
      bus.emit('data:refresh');
    } catch (err) {
      flash(err.message || 'Failed to save', 'error');
    }
    if (btn) { btn.disabled = false; btn.textContent = 'Save Changes'; }
  });

  // Cancel
  document.getElementById('wg-config-cancel')?.addEventListener('click', () => {
    const s = _store.get();
    const wg = (s.data.workgroups || []).find(w => w.id === workgroupId);
    if (wg) {
      bus.emit('nav:org-selected', { orgId: wg.organization_id });
    } else {
      bus.emit('nav:home');
    }
  });

  // Drop zone — accept agents dragged from sidebar
  const dropzone = document.getElementById('wg-agent-dropzone');
  if (dropzone) {
    dropzone.addEventListener('dragover', (e) => {
      if (!e.dataTransfer.types.includes('application/x-teaparty-agent')) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      dropzone.classList.add('wg-agent-dropzone--over');
    });
    dropzone.addEventListener('dragleave', (e) => {
      if (!dropzone.contains(e.relatedTarget)) {
        dropzone.classList.remove('wg-agent-dropzone--over');
      }
    });
    dropzone.addEventListener('drop', async (e) => {
      e.preventDefault();
      dropzone.classList.remove('wg-agent-dropzone--over');
      const raw = e.dataTransfer.getData('application/x-teaparty-agent');
      if (!raw) return;
      let data;
      try { data = JSON.parse(raw); } catch { return; }

      // Don't add if already in this workgroup
      if (data.workgroupId === workgroupId) {
        flash('Agent is already in this team', 'info');
        return;
      }

      dropzone.classList.add('wg-agent-dropzone--loading');
      try {
        await api(`/api/workgroups/${data.workgroupId}/agents/${data.agentId}`, {
          method: 'PATCH',
          body: { workgroup_id: workgroupId },
        });
        flash('Agent added to team', 'success');
        bus.emit('data:refresh');
      } catch (err) {
        flash(err.message || 'Failed to add agent', 'error');
      }
      dropzone.classList.remove('wg-agent-dropzone--loading');
    });
  }

}
