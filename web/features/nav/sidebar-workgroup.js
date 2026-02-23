// Sidebar workgroup section: flat list of workgroup names.
// Clicking a workgroup opens its profile in the main content area.

import { api } from '../../core/api.js';
import { bus } from '../../core/bus.js';
import { escapeHtml } from '../../core/utils.js';
import { avatarColor, initialsFromName } from '../../components/shared/avatar.js';
import { flash } from '../../components/shared/flash.js';
import { loadWorkgroups } from '../data/data-loading.js';

const removeSvg = `<svg viewBox="0 0 20 20" fill="none" width="12" height="12"><path d="M5 5l10 10M15 5L5 15" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>`;

export function renderWorkgroupSections(store, container, orgId, filter) {
  const s = store.get();
  const workgroups = (s.data.workgroups || []).filter(w => w.organization_id === orgId);
  const selection = s.nav.sidebarSelection;

  const currentUserId = s.auth.user?.id;
  const org = (s.data.organizations || []).find(o => o.id === orgId);
  const isOwner = org?.owner_id === currentUserId;

  const sorted = [...workgroups].sort((a, b) => a.name.localeCompare(b.name));

  const filterLower = (filter || '').toLowerCase();
  const filtered = filterLower
    ? sorted.filter(wg => wg.name.toLowerCase().includes(filterLower))
    : sorted;

  if (!filtered.length) {
    container.innerHTML = '<span class="sidebar-empty-inline">No workgroups</span>';
    return;
  }

  const SYSTEM_WORKGROUPS = new Set(['Administration', 'Project Management', 'Engagement']);

  container.innerHTML = filtered.map(wg => {
    const color = avatarColor(wg.name);
    const initials = initialsFromName(wg.name);
    const isActive = selection === `workgroup:${wg.id}`;
    const removeBtn = (isOwner && !SYSTEM_WORKGROUPS.has(wg.name))
      ? `<button class="sidebar-member-remove" data-action="delete-workgroup" data-workgroup-id="${escapeHtml(wg.id)}" data-workgroup-name="${escapeHtml(wg.name)}" title="Delete workgroup" aria-label="Delete ${escapeHtml(wg.name)}">${removeSvg}</button>`
      : '';
    return `<div class="sidebar-nav-item sidebar-wg-item${isActive ? ' active' : ''}">
      <button class="sidebar-wg-select" data-action="select-workgroup" data-workgroup-id="${escapeHtml(wg.id)}" draggable="true" title="${escapeHtml(wg.name)}">
        <span class="sidebar-wg-avatar" style="background:${escapeHtml(color)}">${escapeHtml(initials)}</span><span class="sidebar-nav-label">${escapeHtml(wg.name)}</span>
      </button>
      ${removeBtn}
    </div>`;
  }).join('');

  container.querySelectorAll('[data-action="select-workgroup"]').forEach(btn => {
    btn.addEventListener('click', () => {
      const workgroupId = btn.dataset.workgroupId;
      store.update(s => {
        s.nav.sidebarSelection = `workgroup:${workgroupId}`;
      });
      bus.emit('nav:workgroup-profile', { workgroupId });
    });
    btn.addEventListener('dragstart', (e) => {
      e.dataTransfer.setData('application/x-teaparty-workgroup', JSON.stringify({
        workgroupId: btn.dataset.workgroupId,
      }));
      e.dataTransfer.effectAllowed = 'copy';
      btn.closest('.sidebar-wg-item')?.classList.add('dragging');
    });
    btn.addEventListener('dragend', () => btn.closest('.sidebar-wg-item')?.classList.remove('dragging'));
  });

  container.querySelectorAll('[data-action="delete-workgroup"]').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const workgroupId = btn.dataset.workgroupId;
      const name = btn.dataset.workgroupName;
      if (!confirm(`Delete workgroup "${name}"? This will remove all its conversations, agents, and data.`)) return;
      try {
        await api(`/api/workgroups/${workgroupId}`, { method: 'DELETE' });
        flash(`Workgroup "${name}" deleted`, 'success');
        loadWorkgroups();
      } catch (err) {
        flash(err.message || 'Failed to delete workgroup', 'error');
      }
    });
  });
}
