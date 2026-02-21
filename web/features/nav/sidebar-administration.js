// Sidebar Administration section: admin workspace conversations for the org.

import { bus } from '../../core/bus.js';
import { escapeHtml, jobDisplayName } from '../../core/utils.js';

export function renderAdministrationSection(store, container, orgId, filter) {
  const s = store.get();
  const currentUserId = s.auth.user?.id;
  const org = (s.data.organizations || []).find(o => o.id === orgId);
  if (!org || org.owner_id !== currentUserId) { container.innerHTML = ''; return; }

  const treeData = s.data.treeData || {};

  // Find the Administration workgroup for this org
  const adminWg = (s.data.workgroups || []).find(
    w => w.organization_id === orgId && w.name === 'Administration'
  );
  if (!adminWg) { container.innerHTML = ''; return; }

  const data = treeData[adminWg.id];
  if (!data) { container.innerHTML = ''; return; }

  // Admin conversations are in data.jobs (filtered by kind=admin in data-loading)
  const adminConvs = (data.jobs || []).filter(c => c.kind === 'admin');
  const filterLower = (filter || '').toLowerCase();
  const selection = s.nav.sidebarSelection;

  const filtered = filterLower
    ? adminConvs.filter(c => jobDisplayName(c).toLowerCase().includes(filterLower))
    : adminConvs;

  if (!filtered.length) {
    container.innerHTML = '<span class="sidebar-empty-inline">No admin sessions</span>';
    return;
  }

  container.innerHTML = filtered.map(conv => {
    const name = jobDisplayName(conv);
    const itemId = `admin:${conv.id}`;
    const isActive = selection === itemId;
    return `<button
      class="sidebar-nav-item sidebar-job-item${isActive ? ' active' : ''}"
      data-action="select-admin"
      data-item-id="${escapeHtml(itemId)}"
      data-conversation-id="${escapeHtml(conv.id)}"
      title="${escapeHtml(name)}"
    ><span class="sidebar-nav-hash">#</span><span class="sidebar-nav-label">${escapeHtml(name)}</span></button>`;
  }).join('');

  container.querySelectorAll('[data-action="select-admin"]').forEach(btn => {
    btn.addEventListener('click', () => {
      const itemId = btn.dataset.itemId;
      const conversationId = btn.dataset.conversationId;
      store.update(s => { s.nav.sidebarSelection = itemId; });
      bus.emit('nav:conversation-selected', { workgroupId: adminWg.id, conversationId });
    });
  });
}
