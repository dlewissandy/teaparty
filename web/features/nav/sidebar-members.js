// Sidebar Members section: human members for the active org.
// Fetches from org-level endpoints and shows pending org invites.

import { api } from '../../core/api.js';
import { bus } from '../../core/bus.js';
import { escapeHtml } from '../../core/utils.js';
import { generateHumanSvg } from '../../components/shared/avatar.js';
import { flash } from '../../components/shared/flash.js';

export async function renderMemberSection(store, container, orgId, filter, scopeWgId) {
  const s = store.get();
  const currentUserId = s.auth.user?.id;
  const org = (s.data.organizations || []).find(o => o.id === orgId);
  const isOwner = org?.owner_id === currentUserId;
  const filterLower = (filter || '').toLowerCase();
  const selection = s.nav.sidebarSelection;

  let members = [];
  let invites = [];
  try {
    members = await api(`/api/organizations/${orgId}/org-members`);
    if (isOwner) invites = await api(`/api/organizations/${orgId}/org-invites`);
  } catch { /* fallback empty */ }

  // Optionally filter to a specific workgroup's members
  let filtered = members || [];
  if (scopeWgId) {
    filtered = filtered.filter(m => (m.workgroup_ids || []).includes(scopeWgId));
  }
  if (filterLower) {
    filtered = filtered.filter(m => (m.name || m.email || '').toLowerCase().includes(filterLower));
    invites = invites.filter(inv => (inv.email || '').toLowerCase().includes(filterLower));
  }

  if (!filtered.length && !invites.length) {
    container.innerHTML = '<span class="sidebar-empty-inline">No members</span>';
    return;
  }

  let html = filtered.map(m => {
    const name = m.name || m.email || 'Member';
    const isYou = m.user_id === currentUserId;
    const isMemberOwner = m.role === 'owner';
    const itemId = `member:${m.user_id}`;
    const isActive = selection === itemId;
    const avatarHtml = m.picture
      ? `<img src="${escapeHtml(m.picture)}" alt="" class="sidebar-member-avatar" />`
      : generateHumanSvg(name);

    const removeBtn = (isOwner && !isYou && !isMemberOwner)
      ? `<button class="sidebar-member-remove" data-action="remove-member" data-org-id="${escapeHtml(orgId)}" data-user-id="${escapeHtml(m.user_id)}" data-name="${escapeHtml(name)}" title="Remove member" aria-label="Remove ${escapeHtml(name)}">
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
        ? `<button class="sidebar-member-remove" data-action="cancel-invite" data-org-id="${escapeHtml(orgId)}" data-invite-id="${escapeHtml(inv.id)}" title="Cancel invite" aria-label="Cancel invite for ${escapeHtml(inv.email)}">
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
      const oId = btn.dataset.orgId;
      const userId = btn.dataset.userId;
      const name = btn.dataset.name;
      if (!confirm(`Remove ${name} from this organization?`)) return;
      try {
        await api(`/api/organizations/${oId}/org-members/${userId}`, { method: 'DELETE' });
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
      const oId = btn.dataset.orgId;
      const inviteId = btn.dataset.inviteId;
      if (!confirm('Cancel this invite?')) return;
      try {
        await api(`/api/organizations/${oId}/org-invites/${inviteId}`, { method: 'DELETE' });
        flash('Invite cancelled', 'success');
        bus.emit('data:refresh');
      } catch (err) {
        flash(err.message || 'Failed to cancel invite', 'error');
      }
    });
  });
}
