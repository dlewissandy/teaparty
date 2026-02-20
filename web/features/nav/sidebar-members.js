// Sidebar Members section: human members for the active org or workgroup.
// When scopeWgId is provided, shows members for that workgroup only.
// Otherwise shows members across all workgroups in the org.

import { api } from '../../core/api.js';
import { bus } from '../../core/bus.js';
import { escapeHtml } from '../../core/utils.js';
import { generateHumanSvg } from '../../components/shared/avatar.js';
import { flash } from '../../components/shared/flash.js';

export function renderMemberSection(store, container, orgId, filter, scopeWgId) {
  const s = store.get();
  const workgroups = scopeWgId
    ? (s.data.workgroups || []).filter(w => w.id === scopeWgId)
    : (s.data.workgroups || []).filter(w => w.organization_id === orgId);
  const filterLower = (filter || '').toLowerCase();
  const currentUserId = s.auth.user?.id;
  const selection = s.nav.sidebarSelection;

  // Check if current user is owner of any scoped workgroup
  const isOwner = workgroups.some(wg => wg.owner_id === currentUserId);

  // Collect members with their workgroup ID (for remove API)
  const memberMap = new Map(); // userId -> { member, workgroupId }
  for (const wg of workgroups) {
    const tree = s.data.treeData[wg.id];
    if (!tree) continue;
    for (const m of (tree.members || [])) {
      if (!memberMap.has(m.user_id)) {
        memberMap.set(m.user_id, { member: m, workgroupId: wg.id });
      }
    }
  }

  const entries = Array.from(memberMap.values());
  const filtered = filterLower
    ? entries.filter(e => (e.member.name || e.member.email || '').toLowerCase().includes(filterLower))
    : entries;

  // Collect pending invites across scoped workgroups
  const invites = [];
  for (const wg of workgroups) {
    const tree = s.data.treeData[wg.id];
    if (!tree?.invites) continue;
    for (const inv of tree.invites) {
      if (!filterLower || (inv.email || '').toLowerCase().includes(filterLower)) {
        invites.push({ ...inv, _workgroupId: wg.id });
      }
    }
  }

  if (!filtered.length && !invites.length) {
    container.innerHTML = '<span class="sidebar-empty-inline">No members</span>';
    return;
  }

  let html = filtered.map(({ member: m, workgroupId }) => {
    const name = m.name || m.email || 'Member';
    const isYou = m.user_id === currentUserId;
    const isMemberOwner = m.role === 'owner';
    const itemId = `member:${m.user_id}`;
    const isActive = selection === itemId;
    const avatarHtml = m.picture
      ? `<img src="${escapeHtml(m.picture)}" alt="" class="sidebar-member-avatar" />`
      : generateHumanSvg(name);

    const removeBtn = (isOwner && !isYou && !isMemberOwner)
      ? `<button class="sidebar-member-remove" data-action="remove-member" data-wg-id="${escapeHtml(workgroupId)}" data-user-id="${escapeHtml(m.user_id)}" data-name="${escapeHtml(name)}" title="Remove member" aria-label="Remove ${escapeHtml(name)}">
          <svg viewBox="0 0 20 20" fill="none" width="12" height="12"><path d="M5 5l10 10M15 5L5 15" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
        </button>`
      : '';

    return `<div class="sidebar-nav-item sidebar-member-item${isActive ? ' active' : ''}">
      <button class="sidebar-member-select" data-action="select-member" data-item-id="${escapeHtml(itemId)}" data-user-id="${escapeHtml(m.user_id)}" title="${escapeHtml(name)}">
        <span class="sidebar-member-avatar-wrap">${avatarHtml}</span>
        <span class="sidebar-nav-label">${escapeHtml(name)}${isYou ? ' <span class="sidebar-member-you">(you)</span>' : ''}</span>
      </button>
      ${removeBtn}
    </div>`;
  }).join('');

  if (invites.length) {
    html += `<div class="sidebar-pending-label">Pending Invites</div>`;
    html += invites.map(inv => {
      const cancelBtn = isOwner
        ? `<button class="sidebar-member-remove" data-action="cancel-invite" data-wg-id="${escapeHtml(inv._workgroupId)}" data-invite-id="${escapeHtml(inv.id)}" title="Cancel invite" aria-label="Cancel invite for ${escapeHtml(inv.email)}">
            <svg viewBox="0 0 20 20" fill="none" width="12" height="12"><path d="M5 5l10 10M15 5L5 15" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
          </button>`
        : '';
      return `<div class="sidebar-nav-item sidebar-pending-item" title="${escapeHtml(inv.email)}">
        <span class="sidebar-pending-icon">
          <svg viewBox="0 0 20 20" fill="none" width="14" height="14"><path d="M2 4h16v12H2z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/><path d="M2 4l8 6 8-6" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>
        </span>
        <span class="sidebar-nav-label">${escapeHtml(inv.email)}</span>
        <span class="sidebar-pending-badge">Invited</span>
        ${cancelBtn}
      </div>`;
    }).join('');
  }

  container.innerHTML = html;

  // Wire select-member clicks
  container.querySelectorAll('[data-action="select-member"]').forEach(btn => {
    btn.addEventListener('click', () => {
      const itemId = btn.dataset.itemId;
      store.update(s => { s.nav.sidebarSelection = itemId; });
      bus.emit('nav:member-selected', { userId: btn.dataset.userId });
    });
  });

  // Wire remove-member clicks
  container.querySelectorAll('[data-action="remove-member"]').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const wgId = btn.dataset.wgId;
      const userId = btn.dataset.userId;
      const name = btn.dataset.name;
      if (!confirm(`Remove ${name} from this workgroup?`)) return;
      try {
        await api(`/api/workgroups/${wgId}/members/${userId}`, { method: 'DELETE' });
        flash(`${name} removed`, 'success');
        bus.emit('data:refresh');
      } catch (err) {
        flash(err.message || 'Failed to remove member', 'error');
      }
    });
  });

  // Wire cancel-invite clicks
  container.querySelectorAll('[data-action="cancel-invite"]').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const wgId = btn.dataset.wgId;
      const inviteId = btn.dataset.inviteId;
      if (!confirm('Cancel this invite?')) return;
      try {
        await api(`/api/workgroups/${wgId}/invites/${inviteId}`, { method: 'DELETE' });
        flash('Invite cancelled', 'success');
        bus.emit('data:refresh');
      } catch (err) {
        flash(err.message || 'Failed to cancel invite', 'error');
      }
    });
  });
}
