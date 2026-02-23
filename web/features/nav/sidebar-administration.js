// Sidebar Administration section: admin workspace conversations for the org.

import { api } from '../../core/api.js';
import { bus } from '../../core/bus.js';
import { escapeHtml, jobDisplayName } from '../../core/utils.js';
import { flash } from '../../components/shared/flash.js';

const removeSvg = `<svg viewBox="0 0 20 20" fill="none" width="12" height="12"><path d="M5 5l10 10M15 5L5 15" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>`;

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
    return `<div class="sidebar-nav-item sidebar-job-item${isActive ? ' active' : ''}">
      <button class="sidebar-wg-select" data-action="select-admin" data-item-id="${escapeHtml(itemId)}" data-conversation-id="${escapeHtml(conv.id)}" title="${escapeHtml(name)}">
        <span class="sidebar-nav-hash">#</span><span class="sidebar-nav-label">${escapeHtml(name)}</span>
      </button>
      <button class="sidebar-member-remove" data-action="delete-admin-session" data-conversation-id="${escapeHtml(conv.id)}" data-workgroup-id="${escapeHtml(adminWg.id)}" title="Delete session" aria-label="Delete ${escapeHtml(name)}">${removeSvg}</button>
    </div>`;
  }).join('');

  container.querySelectorAll('[data-action="select-admin"]').forEach(btn => {
    btn.addEventListener('click', () => {
      const itemId = btn.dataset.itemId;
      const conversationId = btn.dataset.conversationId;
      store.update(s => { s.nav.sidebarSelection = itemId; });
      bus.emit('nav:conversation-selected', { workgroupId: adminWg.id, conversationId });
    });
  });

  container.querySelectorAll('[data-action="delete-admin-session"]').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const conversationId = btn.dataset.conversationId;
      const workgroupId = btn.dataset.workgroupId;
      if (!confirm('Delete this session?')) return;
      try {
        await api(`/api/workgroups/${workgroupId}/conversations/${conversationId}`, { method: 'DELETE' });
        btn.closest('.sidebar-nav-item')?.remove();
      } catch (err) {
        flash(err.message || 'Failed to delete session', 'error');
      }
    });
  });
}
