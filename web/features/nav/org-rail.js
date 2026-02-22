// Org rail: left column with org icons, add menu, and user avatar.
// Renders org icons, handles org selection, and context-sensitive add menu.

import { api } from '../../core/api.js';
import { bus } from '../../core/bus.js';
import { escapeHtml } from '../../core/utils.js';
import { avatarColor, initialsFromName } from '../../components/shared/avatar.js';
import { flash } from '../../components/shared/flash.js';

let _store = null;

export function initOrgRail(store) {
  _store = store;

  store.on('data.organizations', renderOrgIcons);
  store.on('data.invites', renderOrgIcons);
  store.on('nav.activeOrgId', () => {
    updateActiveIndicator();
    updateAddMenuItems();
  });

  // Add menu toggle
  const addBtn = document.getElementById('org-rail-add');
  const addMenu = document.getElementById('add-menu');
  if (addBtn && addMenu) {
    addBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      const isHidden = addMenu.classList.contains('hidden');
      addMenu.classList.toggle('hidden', !isHidden);
      if (isHidden) updateAddMenuItems();
    });

    // Close on outside click
    document.addEventListener('click', (e) => {
      if (!addMenu.contains(e.target) && e.target !== addBtn) {
        addMenu.classList.add('hidden');
      }
    });

    // Wire up menu item actions
    addMenu.querySelectorAll('.add-menu-item').forEach(item => {
      item.addEventListener('click', () => {
        addMenu.classList.add('hidden');
        handleAddAction(item.dataset.action);
      });
    });
  }

  // Brand mark = Home button
  document.getElementById('brand-mark-btn')?.addEventListener('click', () => {
    _store.update(s => {
      s.nav.activeOrgId = '';
      s.nav.sidebarSelection = '';
    });
    bus.emit('nav:home');
  });

  renderOrgIcons();
}

function updateAddMenuItems() {
  const hasOrg = !!_store.get().nav.activeOrgId;
  document.querySelectorAll('.add-menu-org-item').forEach(el => {
    const isHomeItem = el.classList.contains('add-menu-home-item');
    el.style.display = (hasOrg || isHomeItem) ? '' : 'none';
  });
}

async function handleAddAction(action) {
  const s = _store.get();
  const orgId = s.nav.activeOrgId;

  switch (action) {
    case 'new-org':
      await handleNewOrg();
      break;
    case 'new-member':
      if (orgId) bus.emit('nav:invite-member', { orgId });
      break;
    case 'new-workgroup':
      if (orgId) bus.emit('nav:create-workgroup', { orgId });
      break;
    case 'new-workflow':
      if (orgId) bus.emit('nav:create-workflow', { orgId });
      break;
    case 'new-agent':
      if (orgId) bus.emit('nav:create-agent', { orgId });
      break;
    case 'new-skill':
      if (orgId) bus.emit('nav:create-skill', { orgId });
      break;
    case 'new-project':
      if (orgId) bus.emit('nav:create-project', { orgId });
      break;
case 'new-engagement':
      bus.emit('nav:create-engagement', { orgId });
      break;
  }
}

function renderOrgIcons() {
  const container = document.getElementById('org-rail-orgs');
  if (!container) return;

  const s = _store.get();
  const orgs = s.data.organizations || [];
  const invites = s.data.invites || [];
  const activeOrgId = s.nav.activeOrgId;
  const memberOrgIds = new Set(orgs.map(o => o.id));

  if (!orgs.length && !invites.length) {
    container.innerHTML = '';
    return;
  }

  let html = '';

  // Render member orgs
  html += orgs.map(org => {
    const name = org.name || 'Org';
    const initials = initialsFromName(name);
    const color = avatarColor(name);
    const isActive = org.id === activeOrgId;
    const hasUnread = orgHasUnread(org.id, s);

    const iconInner = org.icon_url
      ? `<span class="org-rail-icon-inner"><img src="${escapeHtml(org.icon_url)}" alt="" style="width:72px;height:72px;object-fit:cover;display:block" /></span>`
      : `<span class="org-rail-icon-inner" style="background:${escapeHtml(color)}">${escapeHtml(initials)}</span>`;

    return `<button
      class="org-rail-icon${isActive ? ' active' : ''}"
      data-org-id="${escapeHtml(org.id)}"
      title="${escapeHtml(name)}"
      aria-label="${escapeHtml(name)}"
      aria-pressed="${isActive}"
      style="--org-color: ${escapeHtml(color)}"
    >
      ${iconInner}
      ${hasUnread ? '<span class="org-rail-unread-dot" aria-hidden="true"></span>' : ''}
    </button>`;
  }).join('');

  // Render pending invite orgs (skip if already a member)
  const pendingInvites = invites.filter(inv => !memberOrgIds.has(inv.organization_id));
  html += pendingInvites.map(inv => {
    const name = inv.organization_name || 'Org';
    const initials = initialsFromName(name);
    const color = avatarColor(name);

    return `<button
      class="org-rail-icon pending"
      data-org-id="${escapeHtml(inv.organization_id)}"
      title="${escapeHtml(name)} (pending invite)"
      aria-label="${escapeHtml(name)} pending invite"
      style="--org-color: ${escapeHtml(color)}"
    >
      <span class="org-rail-icon-inner" style="background:${escapeHtml(color)}">${escapeHtml(initials)}</span>
      <span class="org-rail-pending-dot" aria-hidden="true"></span>
    </button>`;
  }).join('');

  container.innerHTML = html;

  // Wire all org icon clicks (both member and pending invite)
  container.querySelectorAll('.org-rail-icon').forEach(btn => {
    btn.addEventListener('click', () => {
      const orgId = btn.dataset.orgId;
      _store.update(s => {
        s.nav.activeOrgId = orgId;
        s.nav.activeWorkgroupId = '';
        s.nav.activeConversationId = '';
        s.nav.sidebarSelection = '';
      });
      _store.notify('nav.activeOrgId');
      bus.emit('nav:org-selected', { orgId });
    });
  });
}

function updateActiveIndicator() {
  const s = _store.get();
  const activeOrgId = s.nav.activeOrgId;
  const container = document.getElementById('org-rail-orgs');
  if (!container) return;

  container.querySelectorAll('.org-rail-icon').forEach(btn => {
    const isActive = btn.dataset.orgId === activeOrgId;
    btn.classList.toggle('active', isActive);
    btn.setAttribute('aria-pressed', String(isActive));
  });
}

function orgHasUnread(orgId, s) {
  const user = s.auth.user;
  if (!user) return false;
  const workgroups = (s.data.workgroups || []).filter(w => w.organization_id === orgId);
  for (const wg of workgroups) {
    const tree = s.data.treeData[wg.id];
    if (!tree) continue;
    const convs = [...(tree.jobs || []), ...(tree.directs || [])];
    for (const conv of convs) {
      if (isConversationUnread(conv, user)) return true;
    }
  }
  return false;
}

function isConversationUnread(conversation, user) {
  if (!conversation.latest_message_at) return false;
  const prefs = user?.preferences || {};
  const lastRead = prefs.conversationLastRead?.[conversation.id];
  if (!lastRead) return true;
  const latestMs = new Date(conversation.latest_message_at + (conversation.latest_message_at.match(/Z|[+-]\d{2}/) ? '' : 'Z')).getTime();
  const readMs = new Date(lastRead + (lastRead.match(/Z|[+-]\d{2}/) ? '' : 'Z')).getTime();
  return latestMs > readMs;
}

async function handleNewOrg() {
  const name = prompt('Organization name:');
  if (!name?.trim()) return;
  try {
    const org = await api('/api/organizations', {
      method: 'POST',
      body: { name: name.trim() },
    });
    _store.update(s => {
      s.data.organizations = [...s.data.organizations, org];
    });
    _store.update(s => { s.nav.activeOrgId = org.id; });
    bus.emit('nav:org-selected', { orgId: org.id });
    flash(`Created "${org.name}"`, 'success');
  } catch (e) {
    flash(e.message || 'Failed to create organization', 'error');
  }
}
