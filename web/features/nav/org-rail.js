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
    el.style.display = hasOrg ? '' : 'none';
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
    case 'new-partner':
      if (orgId) bus.emit('nav:create-partner', { orgId });
      break;
    case 'new-engagement':
      if (orgId) bus.emit('nav:create-engagement', { orgId });
      break;
  }
}

function renderOrgIcons() {
  const container = document.getElementById('org-rail-orgs');
  if (!container) return;

  const s = _store.get();
  const orgs = s.data.organizations || [];
  const activeOrgId = s.nav.activeOrgId;

  if (!orgs.length) {
    container.innerHTML = '';
    return;
  }

  container.innerHTML = orgs.map(org => {
    const name = org.name || 'Org';
    const initials = initialsFromName(name);
    const color = avatarColor(name);
    const isActive = org.id === activeOrgId;
    const hasUnread = orgHasUnread(org.id, s);

    return `<button
      class="org-rail-icon${isActive ? ' active' : ''}"
      data-org-id="${escapeHtml(org.id)}"
      title="${escapeHtml(name)}"
      aria-label="${escapeHtml(name)}"
      aria-pressed="${isActive}"
      style="--org-color: ${escapeHtml(color)}"
    >
      <span class="org-rail-icon-inner" style="background:${escapeHtml(color)}">${escapeHtml(initials)}</span>
      ${hasUnread ? '<span class="org-rail-unread-dot" aria-hidden="true"></span>' : ''}
    </button>`;
  }).join('');

  container.querySelectorAll('.org-rail-icon').forEach(btn => {
    btn.addEventListener('click', () => {
      const orgId = btn.dataset.orgId;
      _store.update(s => { s.nav.activeOrgId = orgId; });
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
