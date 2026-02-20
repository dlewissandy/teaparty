// Sidebar Members section: human members for the active org or workgroup.
// When scopeWgId is provided, shows members for that workgroup only.
// Otherwise shows members across all workgroups in the org.

import { bus } from '../../core/bus.js';
import { escapeHtml } from '../../core/utils.js';
import { generateHumanSvg } from '../../components/shared/avatar.js';

export function renderMemberSection(store, container, orgId, filter, scopeWgId) {
  const s = store.get();
  const workgroups = scopeWgId
    ? (s.data.workgroups || []).filter(w => w.id === scopeWgId)
    : (s.data.workgroups || []).filter(w => w.organization_id === orgId);
  const filterLower = (filter || '').toLowerCase();
  const currentUserId = s.auth.user?.id;
  const selection = s.nav.sidebarSelection;

  const memberMap = new Map();
  for (const wg of workgroups) {
    const tree = s.data.treeData[wg.id];
    if (!tree) continue;
    for (const m of (tree.members || [])) {
      if (!memberMap.has(m.user_id)) {
        memberMap.set(m.user_id, m);
      }
    }
  }

  const members = Array.from(memberMap.values());
  const filtered = filterLower
    ? members.filter(m => (m.name || m.email || '').toLowerCase().includes(filterLower))
    : members;

  if (!filtered.length) {
    container.innerHTML = '<span class="sidebar-empty-inline">No members</span>';
    return;
  }

  container.innerHTML = filtered.map(m => {
    const name = m.name || m.email || 'Member';
    const isYou = m.user_id === currentUserId;
    const itemId = `member:${m.user_id}`;
    const isActive = selection === itemId;
    const avatarHtml = m.picture
      ? `<img src="${escapeHtml(m.picture)}" alt="" class="sidebar-member-avatar" />`
      : generateHumanSvg(name);

    return `<button class="sidebar-nav-item sidebar-member-item${isActive ? ' active' : ''}" data-action="select-member" data-item-id="${escapeHtml(itemId)}" data-user-id="${escapeHtml(m.user_id)}" title="${escapeHtml(name)}">
      <span class="sidebar-member-avatar-wrap">${avatarHtml}</span>
      <span class="sidebar-nav-label">${escapeHtml(name)}${isYou ? ' <span class="sidebar-member-you">(you)</span>' : ''}</span>
    </button>`;
  }).join('');

  container.querySelectorAll('[data-action="select-member"]').forEach(btn => {
    btn.addEventListener('click', () => {
      const itemId = btn.dataset.itemId;
      store.update(s => { s.nav.sidebarSelection = itemId; });
      bus.emit('nav:member-selected', { userId: btn.dataset.userId });
    });
  });
}
