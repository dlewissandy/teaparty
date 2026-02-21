// Sidebar container: 260px dark panel with collapsible sections.
// Coordinates sub-components and reacts to org selection.

import { bus } from '../../core/bus.js';
import { api } from '../../core/api.js';
import { escapeHtml } from '../../core/utils.js';
import { avatarColor, initialsFromName } from '../../components/shared/avatar.js';
import { flash } from '../../components/shared/flash.js';
import { loadMyInvites } from '../data/data-loading.js';
import { renderWorkgroupSections } from './sidebar-workgroup.js';
import { renderAgentSection } from './sidebar-agents.js';
import { renderJobSection } from './sidebar-jobs.js';
import { renderPartnerSection } from './sidebar-partnerships.js';
import { renderEngagementSection } from './sidebar-engagements.js';
import { renderProjectSection } from './sidebar-projects.js';
import { renderMemberSection } from './sidebar-members.js';

const STORAGE_KEY = 'teaparty_sidebar_collapsed';

let _store = null;
let _drilledWorkgroupId = '';  // only set by explicit workgroup drill-in

function loadCollapsed() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY)) || [];
  } catch { return []; }
}

function saveCollapsed() {
  const collapsed = [];
  document.querySelectorAll('.sidebar-section-header').forEach(btn => {
    if (btn.getAttribute('aria-expanded') === 'false') {
      const section = btn.dataset.section;
      if (section) collapsed.push(section);
    }
  });
  localStorage.setItem(STORAGE_KEY, JSON.stringify(collapsed));
}

export function initSidebar(store) {
  _store = store;

  // Restore collapsed sections from localStorage
  const collapsed = new Set(loadCollapsed());
  document.querySelectorAll('.sidebar-section-header').forEach(btn => {
    const section = btn.dataset.section;
    if (section && collapsed.has(section)) {
      btn.setAttribute('aria-expanded', 'false');
      const body = btn.closest('.sidebar-section')?.querySelector('.sidebar-section-body');
      if (body) body.classList.add('collapsed');
    }
  });

  // Section collapse toggles (wired once — sections always exist in DOM)
  document.querySelectorAll('.sidebar-section-header').forEach(btn => {
    btn.addEventListener('click', () => {
      const body = btn.closest('.sidebar-section')?.querySelector('.sidebar-section-body');
      const expanded = btn.getAttribute('aria-expanded') !== 'false';
      btn.setAttribute('aria-expanded', String(!expanded));
      if (body) body.classList.toggle('collapsed', expanded);
      saveCollapsed();
    });
  });

  // Search filter
  const searchInput = document.getElementById('sidebar-search');
  if (searchInput) {
    searchInput.addEventListener('input', () => {
      renderSidebar(_store.get().nav.activeOrgId, searchInput.value.trim());
    });
  }

  // Settings button — context-sensitive: workgroup settings when drilled-in, else org settings
  document.getElementById('sidebar-settings-btn')?.addEventListener('click', () => {
    const orgId = _store.get().nav.activeOrgId;
    if (_drilledWorkgroupId) {
      bus.emit('nav:workgroup-settings', { workgroupId: _drilledWorkgroupId, orgId });
    } else if (orgId) {
      bus.emit('nav:org-settings', { orgId });
    }
  });

  // Explicit workgroup drill-in
  bus.on('nav:workgroup-selected', ({ workgroupId }) => {
    _drilledWorkgroupId = workgroupId || '';
    refreshSidebar();
  });

  // Drill-out when navigating to org or home
  bus.on('nav:org-selected', () => {
    _drilledWorkgroupId = '';
    refreshSidebar();
  });
  bus.on('nav:home', () => {
    _drilledWorkgroupId = '';
    refreshSidebar();
  });

  // Re-render when org selection changes
  store.on('nav.activeOrgId', (s) => {
    _drilledWorkgroupId = '';
    const searchInput = document.getElementById('sidebar-search');
    const filter = searchInput?.value.trim() || '';
    renderSidebar(s.nav.activeOrgId, filter);
  });

  // Re-render when data changes
  store.on('data.organizations', () => refreshSidebar());
  store.on('data.workgroups', () => refreshSidebar());
  store.on('data.treeData', () => refreshSidebar());
  store.on('data.partnerships', () => refreshSidebar());
  store.on('data.invites', () => refreshSidebar());
  store.on('conversation.thinkingByConversation', () => refreshSidebar());
  store.on('nav.activeConversationId', () => refreshSidebar());
  store.on('nav.sidebarSelection', () => refreshSidebar());

  renderSidebar(_store.get().nav.activeOrgId, '');
}

function refreshSidebar() {
  const s = _store.get();
  const searchInput = document.getElementById('sidebar-search');
  const filter = searchInput?.value.trim() || '';
  renderSidebar(s.nav.activeOrgId, filter);
}

function renderSidebar(orgId, filter) {
  const s = _store.get();
  const orgs = s.data.organizations || [];

  // Update org name / breadcrumb in sidebar header
  const orgNameEl = document.getElementById('sidebar-org-name');
  const settingsBtn = document.getElementById('sidebar-settings-btn');
  const invites = s.data.invites || [];
  const hasOrgsOrInvites = orgs.length || invites.length;
  const isHome = !orgId && s.auth.user && hasOrgsOrInvites;
  const activeWgId = _drilledWorkgroupId;

  if (orgNameEl) {
    if (orgId && activeWgId) {
      const org = orgs.find(o => o.id === orgId);
      const wg = (s.data.workgroups || []).find(w => w.id === activeWgId);
      const orgName = org?.name || 'Org';
      const wgName = wg?.name || 'Workgroup';
      orgNameEl.innerHTML = `<span id="sidebar-breadcrumb-org" class="sidebar-breadcrumb-link">${escapeHtml(orgName)}</span> <span class="sidebar-breadcrumb-sep">&rsaquo;</span> ${escapeHtml(wgName)}`;
      // Wire up org breadcrumb click
      document.getElementById('sidebar-breadcrumb-org')?.addEventListener('click', () => {
        _drilledWorkgroupId = '';
        _store.update(s => {
          s.nav.activeWorkgroupId = '';
          s.nav.activeConversationId = '';
          s.nav.sidebarSelection = '';
        });
      });
    } else if (orgId) {
      const org = orgs.find(o => o.id === orgId);
      const invite = invites.find(inv => inv.organization_id === orgId);
      orgNameEl.textContent = org?.name || invite?.organization_name || 'TeaParty';
    } else {
      orgNameEl.textContent = 'TeaParty';
    }
  }

  // Hide settings gear on home view
  if (settingsBtn) settingsBtn.style.display = isHome ? 'none' : '';

  if (!s.auth.user || !hasOrgsOrInvites) {
    showNoOrgsPlaceholder();
    return;
  }

  // Hide the no-orgs placeholder if it exists
  const noOrgsEl = document.getElementById('sidebar-no-orgs');
  if (noOrgsEl) noOrgsEl.style.display = 'none';

  // All possible sidebar sections
  const allSections = [
    'sidebar-organizations', 'sidebar-workgroups', 'sidebar-agents',
    'sidebar-jobs', 'sidebar-partners', 'sidebar-engagements', 'sidebar-projects',
    'sidebar-members',
  ];

  // Pending invite: show accept/decline banner instead of sections
  const pendingInvite = orgId && !orgs.find(o => o.id === orgId)
    ? invites.find(inv => inv.organization_id === orgId)
    : null;
  if (pendingInvite) {
    for (const id of allSections) {
      const el = document.getElementById(id);
      if (el) el.style.display = 'none';
    }
    clearContainers();
    showInviteBanner(pendingInvite);
    if (settingsBtn) settingsBtn.style.display = 'none';
    return;
  }
  hideInviteBanner();

  // Determine which mode we're in and which sections to show
  const isWorkgroup = !!(orgId && activeWgId);
  let visibleSections;

  if (isHome) {
    visibleSections = ['sidebar-organizations', 'sidebar-partners', 'sidebar-engagements'];
  } else if (isWorkgroup) {
    visibleSections = ['sidebar-agents', 'sidebar-jobs', 'sidebar-members'];
  } else if (orgId) {
    visibleSections = ['sidebar-workgroups', 'sidebar-agents', 'sidebar-partners', 'sidebar-engagements', 'sidebar-projects', 'sidebar-members'];
  } else {
    clearContainers();
    return;
  }

  // Toggle section visibility
  const visibleSet = new Set(visibleSections);
  for (const id of allSections) {
    const el = document.getElementById(id);
    if (el) el.style.display = visibleSet.has(id) ? '' : 'none';
  }

  if (isHome) {
    const orgContainer = document.getElementById('sidebar-organizations-list');
    const partnerContainer = document.getElementById('sidebar-partners-list');
    const engContainer = document.getElementById('sidebar-engagements-list');

    if (orgContainer) renderOrganizations(_store, orgContainer, filter);
    if (partnerContainer) renderAllPartnerships(_store, partnerContainer, filter);
    if (engContainer) renderAllEngagements(_store, engContainer, filter);
    return;
  }

  if (isWorkgroup) {
    // Workgroup mode: agents, jobs, members scoped to this workgroup
    const agentContainer = document.getElementById('sidebar-agents-list');
    const jobContainer = document.getElementById('sidebar-jobs-list');
    const memberContainer = document.getElementById('sidebar-members-list');

    if (agentContainer) renderAgentSection(_store, agentContainer, orgId, filter, activeWgId);
    if (jobContainer) renderJobSection(_store, jobContainer, activeWgId, filter);
    if (memberContainer) renderMemberSection(_store, memberContainer, orgId, filter, activeWgId);
    return;
  }

  // Org mode
  const wgContainer = document.getElementById('sidebar-workgroups-list');
  const agentContainer = document.getElementById('sidebar-agents-list');
  const partnerContainer = document.getElementById('sidebar-partners-list');
  const engContainer = document.getElementById('sidebar-engagements-list');
  const projContainer = document.getElementById('sidebar-projects-list');
  const memberContainer = document.getElementById('sidebar-members-list');

  if (wgContainer) renderWorkgroupSections(_store, wgContainer, orgId, filter);
  if (agentContainer) renderAgentSection(_store, agentContainer, orgId, filter);
  if (partnerContainer) renderPartnerSection(_store, partnerContainer, orgId, filter);
  if (engContainer) renderEngagementSection(_store, engContainer, orgId, filter);
  if (projContainer) renderProjectSection(_store, projContainer, orgId, filter);
  if (memberContainer) renderMemberSection(_store, memberContainer, orgId, filter);
}

function showNoOrgsPlaceholder() {
  hideInviteBanner();

  // Hide all section headers
  const allSections = [
    'sidebar-organizations', 'sidebar-workgroups', 'sidebar-agents',
    'sidebar-jobs', 'sidebar-partners', 'sidebar-engagements', 'sidebar-projects',
    'sidebar-members',
  ];
  for (const id of allSections) {
    const el = document.getElementById(id);
    if (el) el.style.display = 'none';
  }

  // Clear all list contents
  [...allSections.map(id => id + '-list')].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.innerHTML = '';
  });

  // Show the placeholder message in the sidebar content area
  const sidebarContent = document.getElementById('sidebar-content');
  let placeholder = document.getElementById('sidebar-no-orgs');
  if (!placeholder && sidebarContent) {
    placeholder = document.createElement('div');
    placeholder.id = 'sidebar-no-orgs';
    placeholder.className = 'sidebar-empty-state';
    placeholder.innerHTML = `
      <p>Create an organization to begin.</p>
      <p class="meta">Click the <strong>+</strong> button to get started.</p>
    `;
    sidebarContent.appendChild(placeholder);
  }
  if (placeholder) placeholder.style.display = '';
}

function clearContainers() {
  ['sidebar-organizations-list', 'sidebar-engagements-list', 'sidebar-workgroups-list', 'sidebar-agents-list', 'sidebar-partners-list', 'sidebar-projects-list', 'sidebar-members-list'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.innerHTML = '';
  });
}

function showInviteBanner(invite) {
  const sidebarContent = document.getElementById('sidebar-content');
  if (!sidebarContent) return;

  let banner = document.getElementById('sidebar-invite-banner');
  if (!banner) {
    banner = document.createElement('div');
    banner.id = 'sidebar-invite-banner';
    const header = sidebarContent.querySelector('.sidebar-header');
    if (header) {
      header.after(banner);
    } else {
      sidebarContent.prepend(banner);
    }
  }

  const inviterName = invite.invited_by_name || 'Someone';
  const orgName = invite.organization_name || 'this organization';

  banner.className = 'sidebar-invite-banner';
  banner.innerHTML = `
    <p class="sidebar-invite-message"><strong>${escapeHtml(inviterName)}</strong> invited you to join <strong>${escapeHtml(orgName)}</strong></p>
    <div class="sidebar-invite-actions">
      <button class="btn-primary sidebar-invite-accept" data-action="accept">Accept</button>
      <button class="btn-ghost sidebar-invite-decline" data-action="decline">Decline</button>
    </div>
  `;
  banner.style.display = '';

  banner.querySelector('[data-action="accept"]').addEventListener('click', async () => {
    try {
      await api(`/api/organizations/${invite.organization_id}/org-invites/${invite.token}/accept`, { method: 'POST' });
      flash(`Joined ${orgName}`, 'success');
      await loadMyInvites();
      bus.emit('data:refresh');
    } catch (err) {
      flash(err.message || 'Failed to accept invite', 'error');
    }
  });

  banner.querySelector('[data-action="decline"]').addEventListener('click', async () => {
    try {
      await api(`/api/organizations/${invite.organization_id}/org-invites/${invite.token}/decline`, { method: 'POST' });
      flash('Invite declined', 'info');
      await loadMyInvites();
      _store.update(s => { s.nav.activeOrgId = ''; });
      _store.notify('nav.activeOrgId');
      bus.emit('nav:home');
    } catch (err) {
      flash(err.message || 'Failed to decline invite', 'error');
    }
  });
}

function hideInviteBanner() {
  const banner = document.getElementById('sidebar-invite-banner');
  if (banner) banner.style.display = 'none';
}

// ─── Home mode: cross-org renderers ──────────────────────────────────────────

function renderOrganizations(store, container, filter) {
  const s = store.get();
  const orgs = s.data.organizations || [];
  const filterLower = (filter || '').toLowerCase();
  const selection = s.nav.sidebarSelection;

  const filtered = filterLower
    ? orgs.filter(o => o.name.toLowerCase().includes(filterLower))
    : orgs;

  if (!filtered.length) {
    container.innerHTML = '<span class="sidebar-empty-inline">No organizations</span>';
    return;
  }

  container.innerHTML = filtered.map(org => {
    const color = avatarColor(org.name);
    const initials = initialsFromName(org.name);
    const isActive = selection === `org:${org.id}`;
    return `<button
      class="sidebar-nav-item sidebar-wg-item${isActive ? ' active' : ''}"
      data-action="select-org"
      data-org-id="${escapeHtml(org.id)}"
      title="${escapeHtml(org.name)}"
    ><span class="sidebar-wg-avatar" style="background:${escapeHtml(color)}">${escapeHtml(initials)}</span><span class="sidebar-nav-label">${escapeHtml(org.name)}</span></button>`;
  }).join('');

  container.querySelectorAll('[data-action="select-org"]').forEach(btn => {
    btn.addEventListener('click', () => {
      const orgId = btn.dataset.orgId;
      store.update(s => {
        s.nav.activeOrgId = orgId;
        s.nav.sidebarSelection = '';
      });
      bus.emit('nav:org-selected', { orgId });
    });
  });
}

function renderAllPartnerships(store, container, filter) {
  const s = store.get();
  const partnerships = (s.data.partnerships || []).filter(p => p.status === 'accepted');
  const filterLower = (filter || '').toLowerCase();
  const selection = s.nav.sidebarSelection;

  const items = partnerships.map(p => ({
    id: p.id,
    sourceName: p.source_org_name || '',
    targetName: p.target_org_name || '',
    label: `${p.source_org_name || '?'} \u2194 ${p.target_org_name || '?'}`,
  }));

  const filtered = filterLower
    ? items.filter(p => p.label.toLowerCase().includes(filterLower))
    : items;

  if (!filtered.length) {
    container.innerHTML = '<span class="sidebar-empty-inline">No partnerships</span>';
    return;
  }

  container.innerHTML = filtered.map(p => {
    const isActive = selection === `partner:${p.id}`;
    return `<button class="sidebar-nav-item sidebar-partner-item${isActive ? ' active' : ''}" data-action="select-partner" data-partnership-id="${escapeHtml(p.id)}" title="${escapeHtml(p.label)}">
      <span class="sidebar-nav-label">${escapeHtml(p.label)}</span>
    </button>`;
  }).join('');

  container.querySelectorAll('[data-action="select-partner"]').forEach(btn => {
    btn.addEventListener('click', () => {
      const id = btn.dataset.partnershipId;
      store.update(s => { s.nav.sidebarSelection = `partner:${id}`; });
      bus.emit('nav:partner-selected', { partnershipId: id });
    });
  });
}

function renderAllEngagements(store, container, filter) {
  const s = store.get();
  const filterLower = (filter || '').toLowerCase();
  const selection = s.nav.sidebarSelection;
  const workgroups = s.data.workgroups || [];

  const seen = new Set();
  const engagements = [];

  for (const wg of workgroups) {
    const tree = s.data.treeData[wg.id];
    if (!tree?.engagements) continue;
    for (const eng of tree.engagements) {
      if (seen.has(eng.id)) continue;
      seen.add(eng.id);
      const convId = eng.source_workgroup_id === wg.id
        ? eng.source_conversation_id
        : eng.target_conversation_id;
      engagements.push({ eng, workgroupId: wg.id, convId: convId || '' });
    }
  }

  const filtered = filterLower
    ? engagements.filter(({ eng }) => eng.title.toLowerCase().includes(filterLower))
    : engagements;

  if (!filtered.length) {
    container.innerHTML = '<span class="sidebar-empty-inline">No engagements</span>';
    return;
  }

  container.innerHTML = filtered.map(({ eng, workgroupId, convId }) => {
    const isActive = selection === `engagement:${eng.id}`;
    const status = eng.status || 'proposed';
    const statusLabel = status.charAt(0).toUpperCase() + status.slice(1);
    return `<button class="sidebar-nav-item sidebar-engagement-item${isActive ? ' active' : ''}" data-action="open-engagement" data-workgroup-id="${escapeHtml(workgroupId)}" data-engagement-id="${escapeHtml(eng.id)}" data-conversation-id="${escapeHtml(convId)}" title="${escapeHtml(eng.title)}">
      <span class="sidebar-nav-label">${escapeHtml(eng.title)}</span>
      <span class="sidebar-engagement-badge sidebar-engagement-badge--${escapeHtml(status)}" title="${statusLabel}">${escapeHtml(statusLabel)}</span>
    </button>`;
  }).join('');

  container.querySelectorAll('[data-action="open-engagement"]').forEach(btn => {
    btn.addEventListener('click', () => {
      const workgroupId = btn.dataset.workgroupId;
      const engagementId = btn.dataset.engagementId;
      const conversationId = btn.dataset.conversationId;
      store.update(s => {
        s.nav.sidebarSelection = `engagement:${engagementId}`;
        if (conversationId) {
          s.nav.activeWorkgroupId = workgroupId;
          s.nav.activeConversationId = conversationId;
        }
      });
      bus.emit('nav:engagement-selected', { workgroupId, engagementId, conversationId });
    });
  });
}
