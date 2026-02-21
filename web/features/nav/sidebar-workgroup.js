// Sidebar workgroup section: flat list of workgroup names.

import { bus } from '../../core/bus.js';
import { api } from '../../core/api.js';
import { escapeHtml } from '../../core/utils.js';
import { avatarColor, initialsFromName } from '../../components/shared/avatar.js';

let _store = null;

export function initWorkgroupSettings(store) {
  _store = store;

  bus.on('nav:workgroup-settings', ({ workgroupId }) => {
    openWorkgroupTeamConfig(workgroupId);
  });
}

export function renderWorkgroupSections(store, container, orgId, filter) {
  const s = store.get();
  const workgroups = (s.data.workgroups || []).filter(w => w.organization_id === orgId);
  const selection = s.nav.sidebarSelection;

  // Filter out the auto-created Administration workgroup
  const visible = workgroups.filter(wg => wg.name !== 'Administration');

  const filterLower = (filter || '').toLowerCase();
  const filtered = filterLower
    ? visible.filter(wg => wg.name.toLowerCase().includes(filterLower))
    : visible;

  if (!filtered.length) {
    container.innerHTML = '<span class="sidebar-empty-inline">No workgroups</span>';
    return;
  }

  container.innerHTML = filtered.map(wg => {
    const color = avatarColor(wg.name);
    const initials = initialsFromName(wg.name);
    const isActive = selection === `workgroup:${wg.id}`;
    return `<button
      class="sidebar-nav-item sidebar-wg-item${isActive ? ' active' : ''}"
      data-action="select-workgroup"
      data-workgroup-id="${escapeHtml(wg.id)}"
      title="${escapeHtml(wg.name)}"
    ><span class="sidebar-wg-avatar" style="background:${escapeHtml(color)}">${escapeHtml(initials)}</span><span class="sidebar-nav-label">${escapeHtml(wg.name)}</span></button>`;
  }).join('');

  container.querySelectorAll('[data-action="select-workgroup"]').forEach(btn => {
    btn.addEventListener('click', () => {
      const workgroupId = btn.dataset.workgroupId;
      store.update(s => {
        s.nav.activeWorkgroupId = workgroupId;
        s.nav.sidebarSelection = `workgroup:${workgroupId}`;
      });
      bus.emit('nav:workgroup-selected', { workgroupId });
    });
  });
}


// ─── Workgroup Team Config Settings ─────────────────────────────────────────

const MODEL_OPTIONS = [
  { value: 'claude-sonnet-4-6', label: 'Claude Sonnet 4.6' },
  { value: 'claude-haiku-4-5', label: 'Claude Haiku 4.5' },
  { value: 'claude-opus-4-6', label: 'Claude Opus 4.6' },
];

const PERMISSION_OPTIONS = [
  { value: 'acceptEdits', label: 'Accept Edits' },
  { value: 'plan', label: 'Plan (approval required)' },
  { value: 'bypassPermissions', label: 'Bypass Permissions' },
];

function openWorkgroupTeamConfig(workgroupId) {
  if (!_store) return;
  const s = _store.get();
  const wg = (s.data.workgroups || []).find(w => w.id === workgroupId);
  if (!wg) return;

  const model = wg.team_model || 'claude-sonnet-4-6';
  const permMode = wg.team_permission_mode || 'acceptEdits';
  const maxTurns = wg.team_max_turns ?? 30;
  const maxCost = wg.team_max_cost_usd ?? '';
  const maxTime = wg.team_max_time_seconds ?? '';

  const modelOpts = MODEL_OPTIONS.map(o =>
    `<option value="${o.value}"${o.value === model ? ' selected' : ''}>${escapeHtml(o.label)}</option>`
  ).join('');

  const permOpts = PERMISSION_OPTIONS.map(o =>
    `<option value="${o.value}"${o.value === permMode ? ' selected' : ''}>${escapeHtml(o.label)}</option>`
  ).join('');

  bus.emit('settings:open', {
    title: 'Team Configuration',
    subtitle: wg.name,
    formHtml: `
      <p class="settings-hint">Configure how agent teams run in this workgroup when spawned by projects.</p>
      <label class="settings-field">
        <span class="settings-label">Model</span>
        <select name="team_model">${modelOpts}</select>
      </label>
      <label class="settings-field">
        <span class="settings-label">Permission Mode</span>
        <select name="team_permission_mode">${permOpts}</select>
      </label>
      <label class="settings-field">
        <span class="settings-label">Max Turns</span>
        <input type="number" name="team_max_turns" value="${maxTurns}" min="1" max="500" />
      </label>
      <label class="settings-field">
        <span class="settings-label">Max Cost (USD)</span>
        <input type="number" name="team_max_cost_usd" value="${escapeHtml(String(maxCost))}" min="0" step="0.01" placeholder="No limit" />
      </label>
      <label class="settings-field">
        <span class="settings-label">Max Time (seconds)</span>
        <input type="number" name="team_max_time_seconds" value="${escapeHtml(String(maxTime))}" min="0" step="1" placeholder="No limit" />
      </label>
      <div class="settings-actions">
        <button type="button" class="btn-ghost" data-action="settings-cancel">Cancel</button>
        <button type="submit" class="btn-primary">Save</button>
      </div>
    `,
    onSubmit: async (formData) => {
      const body = {
        team_model: formData.get('team_model'),
        team_permission_mode: formData.get('team_permission_mode'),
        team_max_turns: parseInt(formData.get('team_max_turns'), 10) || 30,
      };
      const costVal = formData.get('team_max_cost_usd');
      body.team_max_cost_usd = costVal ? parseFloat(costVal) : null;
      const timeVal = formData.get('team_max_time_seconds');
      body.team_max_time_seconds = timeVal ? parseInt(timeVal, 10) : null;

      await api(`/api/workgroups/${workgroupId}`, { method: 'PATCH', body });
      bus.emit('data:refresh');
    },
  });
}
