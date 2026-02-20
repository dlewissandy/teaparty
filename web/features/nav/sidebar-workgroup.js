// Sidebar workgroup section: flat list of workgroup names.

import { bus } from '../../core/bus.js';
import { escapeHtml } from '../../core/utils.js';
import { avatarColor, initialsFromName } from '../../components/shared/avatar.js';

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
