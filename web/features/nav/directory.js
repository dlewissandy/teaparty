// Directory: inline view for browsing organizations and people.
// Renders inside #directory-view in main-content, with People/Organizations tabs and search.

import { bus } from '../../core/bus.js';
import { api } from '../../core/api.js';
import { escapeHtml } from '../../core/utils.js';
import { flash } from '../../components/shared/flash.js';
import { loadPartnerships } from '../data/data-loading.js';

let _store = null;
let _activeTab = 'people'; // 'people' | 'orgs'
let _orgs = [];
let _users = [];
let _cacheTime = 0;
let _orgMemberIds = new Map(); // orgId -> Set of user IDs
let _orgInvitedEmails = new Map(); // orgId -> Set of emails

const CACHE_TTL = 30_000;

export function initDirectory(store) {
  _store = store;

  const btn = document.getElementById('sidebar-directory-btn');
  if (btn) btn.addEventListener('click', () => showDirectoryView());

  const input = document.getElementById('directory-input');
  if (input) input.addEventListener('input', () => renderResults(input.value.trim()));

  // Tab switching
  document.querySelectorAll('.directory-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      _activeTab = tab.dataset.tab;
      document.querySelectorAll('.directory-tab').forEach(t => t.classList.toggle('active', t === tab));
      const input = document.getElementById('directory-input');
      renderResults(input?.value.trim() || '');
    });
  });

  bus.on('nav:directory-open', () => showDirectoryView());

  // Re-render when active org changes so invite/partner filters reflect the new org
  store.on('nav.activeOrgId', () => {
    const directoryView = document.getElementById('directory-view');
    if (directoryView && !directoryView.classList.contains('hidden')) {
      invalidateDirectoryCache();
      fetchData().then(() => {
        const input = document.getElementById('directory-input');
        renderResults(input?.value.trim() || '');
      });
    }
  });

  bus.on('nav:directory-refresh', async () => {
    const directoryView = document.getElementById('directory-view');
    if (directoryView && !directoryView.classList.contains('hidden')) {
      await fetchData();
      const input = document.getElementById('directory-input');
      renderResults(input?.value.trim() || '');
    }
  });

  bus.on('nav:invite-member', ({ orgId }) => {
    const s = _store.get();
    const org = (s.data.organizations || []).find(o => o.id === orgId);
    const orgName = org?.name || 'this organization';
    bus.emit('settings:open', {
      title: 'Invite Member',
      subtitle: `Invite a new member to ${orgName}`,
      formHtml: `
        <label class="settings-field">
          <span class="settings-label">Email</span>
          <input type="email" name="email" required placeholder="user@example.com" />
        </label>
        <div class="settings-actions">
          <button type="button" class="btn-ghost" data-action="settings-cancel">Cancel</button>
          <button type="submit" class="btn-primary">Send Invite</button>
        </div>
      `,
      onSubmit: async (formData) => {
        const email = formData.get('email');
        await api(`/api/organizations/${orgId}/org-invites`, { method: 'POST', body: { email } });
        bus.emit('data:refresh');
      },
    });
  });
}

async function fetchData() {
  if (Date.now() - _cacheTime < CACHE_TTL && (_orgs.length || _users.length)) return;
  try {
    const [orgs, users] = await Promise.all([
      api('/api/org-directory'),
      api('/api/user-directory'),
    ]);
    _orgs = orgs || [];
    _users = users || [];
    _cacheTime = Date.now();

    // Fetch org members for orgs the current user owns (for invite filtering)
    const s = _store.get();
    const myOrgs = (s.data.organizations || []).filter(o => o.owner_id === s.auth.user?.id);
    _orgMemberIds = new Map();
    _orgInvitedEmails = new Map();
    await Promise.all(myOrgs.map(async o => {
      try {
        const [members, invites] = await Promise.all([
          api(`/api/organizations/${o.id}/org-members`),
          api(`/api/organizations/${o.id}/org-invites`),
        ]);
        _orgMemberIds.set(o.id, new Set((members || []).map(m => m.user_id)));
        _orgInvitedEmails.set(o.id, new Set((invites || []).map(i => i.email.toLowerCase())));
      } catch { /* skip */ }
    }));
  } catch {
    // keep stale data
  }
}

async function showDirectoryView() {
  const views = ['chat-view', 'home-view', 'agent-profile-view', 'partner-profile-view', 'workgroup-profile-view', 'org-dashboard-view', 'org-settings-view', 'create-project-form'];
  for (const id of views) { document.getElementById(id)?.classList.add('hidden'); }
  document.getElementById('directory-view')?.classList.remove('hidden');
  const input = document.getElementById('directory-input');
  if (input) {
    input.value = '';
    input.focus();
  }

  await fetchData();
  renderResults('');
}

export function hideDirectoryView() {
  const directoryView = document.getElementById('directory-view');
  if (directoryView) directoryView.classList.add('hidden');
}

export function invalidateDirectoryCache() {
  _cacheTime = 0;
}

function buildResults(query) {
  const q = (query || '').toLowerCase();
  const results = [];

  if (_activeTab === 'orgs') {
    for (const org of _orgs) {
      if (!q || org.name.toLowerCase().includes(q) || (org.description || '').toLowerCase().includes(q)) {
        results.push({
          type: 'org', id: org.id, label: org.name,
          sublabel: org.service_description || org.description || '',
          icon_url: org.icon_url || '',
          owner_name: org.owner_name || '',
          partner_count: org.partner_count || 0,
          engagement_count: org.engagement_count || 0,
          avg_rating: org.avg_rating,
        });
      }
    }
  } else {
    for (const user of _users) {
      if (!q || user.name.toLowerCase().includes(q) || user.email.toLowerCase().includes(q)) {
        results.push({
          type: 'person', id: user.id, label: user.name, sublabel: user.email,
          picture: user.picture,
          orgs_owned: user.orgs_owned || 0,
          orgs_member_of: user.orgs_member_of || 0,
          avg_rating: user.avg_rating,
        });
      }
    }
  }

  return results;
}

function renderResults(query) {
  const container = document.getElementById('directory-results');
  if (!container) return;

  const results = buildResults(query);
  const s = _store.get();
  const myOrgs = (s.data.organizations || []).filter(o => o.owner_id === s.auth.user?.id);
  const activeOrgId = s.nav.activeOrgId;

  if (!results.length) {
    container.innerHTML = '<p class="qs-empty">No results</p>';
    return;
  }

  let html = '<div class="directory-grid">';
  for (const item of results) {
    let avatar;
    if (item.type === 'person' && item.picture) {
      avatar = `<img src="${escapeHtml(item.picture)}" class="dir-card-avatar" alt="" />`;
    } else if (item.type === 'org' && item.icon_url) {
      avatar = `<img src="${escapeHtml(item.icon_url)}" class="dir-card-avatar" alt="" />`;
    } else {
      avatar = `<span class="dir-card-icon">${typeIcon(item.type)}</span>`;
    }

    let meta = '';
    if (item.type === 'org') {
      const stars = item.avg_rating != null ? renderStars(item.avg_rating) : '';
      meta = `<span class="dir-card-meta">
        ${item.owner_name ? `<span class="dir-card-owner">${escapeHtml(item.owner_name)}</span>` : ''}
        <span class="dir-card-stats">${item.partner_count} partner${item.partner_count !== 1 ? 's' : ''} &middot; ${item.engagement_count} engagement${item.engagement_count !== 1 ? 's' : ''}</span>
        ${stars}
      </span>`;
    } else if (item.type === 'person') {
      const stars = item.avg_rating != null ? renderStars(item.avg_rating) : '';
      const parts = [];
      if (item.orgs_owned > 0) parts.push(`${item.orgs_owned} owned`);
      if (item.orgs_member_of > 0) parts.push(`${item.orgs_member_of} joined`);
      meta = `<span class="dir-card-meta">
        ${parts.length ? `<span class="dir-card-stats">${parts.join(' &middot; ')}</span>` : ''}
        ${stars}
      </span>`;
    }

    // Hide invite for people already in the org or with a pending invite
    let showInvite = item.type === 'person' && myOrgs.length > 0;
    if (showInvite) {
      const email = (item.sublabel || '').toLowerCase();
      const isTaken = (orgId) =>
        _orgMemberIds.get(orgId)?.has(item.id) || _orgInvitedEmails.get(orgId)?.has(email);

      if (activeOrgId && _orgMemberIds.has(activeOrgId)) {
        showInvite = !isTaken(activeOrgId);
      } else {
        // No active org — hide if person is member/invited in ALL owned orgs
        if (myOrgs.every(o => isTaken(o.id))) showInvite = false;
      }
    }

    // Show "Add Partner" for orgs that aren't the active org and don't already have a partnership (source direction only)
    let showOrgInvite = false;
    if (item.type === 'org' && activeOrgId && item.id !== activeOrgId && myOrgs.some(o => o.id === activeOrgId)) {
      const partnerships = s.data.partnerships || [];
      const hasPartnership = partnerships.some(p =>
        p.status === 'accepted' &&
        p.source_org_id === activeOrgId && p.target_org_id === item.id
      );
      showOrgInvite = !hasPartnership;
    }

    const inviteBtn = showInvite
      ? `<span class="dir-card-invite" data-action="invite-person" data-email="${escapeHtml(item.sublabel)}" data-name="${escapeHtml(item.label)}" title="Invite to organization">Invite</span>`
      : showOrgInvite
        ? `<span class="dir-card-invite" data-action="invite-org" data-org-id="${escapeHtml(item.id)}" data-org-name="${escapeHtml(item.label)}" title="Add as partner">Add Partner</span>`
        : '';

    html += `<button class="dir-card" data-type="${item.type}" data-id="${escapeHtml(item.id)}">
      ${avatar}
      <span class="dir-card-name">${escapeHtml(item.label)}</span>
      <span class="dir-card-detail">${escapeHtml(item.sublabel)}</span>
      ${meta}
      ${inviteBtn}
    </button>`;
  }
  html += '</div>';

  container.innerHTML = html;

  container.querySelectorAll('.dir-card').forEach(btn => {
    btn.addEventListener('click', () => {
      activateResult(btn.dataset.type, btn.dataset.id);
    });
  });

  container.querySelectorAll('[data-action="invite-person"]').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const email = btn.dataset.email;
      const name = btn.dataset.name;
      const targetOrgId = activeOrgId && myOrgs.find(o => o.id === activeOrgId)
        ? activeOrgId : myOrgs[0]?.id;
      if (!targetOrgId) return;
      btn.textContent = 'Sending...';
      btn.style.pointerEvents = 'none';
      try {
        await api(`/api/organizations/${targetOrgId}/org-invites`, { method: 'POST', body: { email } });
        const orgName = myOrgs.find(o => o.id === targetOrgId)?.name || 'organization';
        flash(`Invited ${name} to ${orgName}`, 'success');
        btn.textContent = 'Invited';
        // Update local cache so button won't reappear on next render
        if (!_orgInvitedEmails.has(targetOrgId)) _orgInvitedEmails.set(targetOrgId, new Set());
        _orgInvitedEmails.get(targetOrgId).add(email.toLowerCase());
      } catch (err) {
        flash(err.message || 'Failed to send invite', 'error');
        btn.textContent = 'Invite';
        btn.style.pointerEvents = '';
      }
    });
  });

  container.querySelectorAll('[data-action="invite-org"]').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const targetOrgId = btn.dataset.orgId;
      const targetOrgName = btn.dataset.orgName;
      if (!activeOrgId) return;
      btn.textContent = 'Sending...';
      btn.style.pointerEvents = 'none';
      try {
        await api('/api/partnerships', {
          method: 'POST',
          body: { source_org_id: activeOrgId, target_org_id: targetOrgId },
        });
        flash(`Added ${targetOrgName} as partner`, 'success');
        btn.textContent = 'Partner';
        if (activeOrgId) loadPartnerships(activeOrgId);
        invalidateDirectoryCache();
      } catch (err) {
        flash(err.message || 'Failed to add partner', 'error');
        btn.textContent = 'Invite';
        btn.style.pointerEvents = '';
      }
    });
  });
}

function activateResult(type, id) {
  hideDirectoryView();

  if (type === 'org') {
    _store.update(s => { s.nav.activeOrgId = id; });
    _store.notify('nav.activeOrgId');
    bus.emit('nav:org-selected', { orgId: id });
  }
  // People: navigate home for now (no dedicated person view yet)
  if (type === 'person') {
    bus.emit('nav:home');
  }
}

function renderStars(rating) {
  const full = Math.floor(rating);
  const half = rating - full >= 0.5 ? 1 : 0;
  const empty = 5 - full - half;
  const star = (cls) => `<svg class="dir-star ${cls}" viewBox="0 0 20 20" width="14" height="14"><path d="M10 2l2.09 4.26L17 7.27l-3.5 3.41.83 4.82L10 13.27l-4.33 2.23.83-4.82L3 7.27l4.91-1.01L10 2z" /></svg>`;
  return `<span class="dir-card-stars" title="${rating} / 5">${star('filled').repeat(full)}${half ? star('half') : ''}${star('empty').repeat(empty)}</span>`;
}

function typeIcon(type) {
  if (type === 'org') {
    return `<svg viewBox="0 0 20 20" fill="none" width="28" height="28"><path d="M3 5a2 2 0 012-2h10a2 2 0 012 2v10a2 2 0 01-2 2H5a2 2 0 01-2-2V5z" stroke="currentColor" stroke-width="1.5"/><path d="M7 8h6M7 11h4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>`;
  }
  if (type === 'person') {
    return `<svg viewBox="0 0 20 20" fill="none" width="28" height="28"><circle cx="10" cy="7" r="3" stroke="currentColor" stroke-width="1.4"/><path d="M4 17c0-3.3 2.7-6 6-6s6 2.7 6 6" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>`;
  }
  return '';
}
