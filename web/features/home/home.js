// Home dashboard: org cards, activity feed, welcome state.
// Ported from modules/home.js and modules/org-view.js.

import { api } from '../../core/api.js';
import { bus } from '../../core/bus.js';
import { escapeHtml } from '../../core/utils.js';

let _store = null;

export function initHome(store) {
  _store = store;

  // Listen for home navigation
  bus.on('nav:home', () => renderHome());

  // Re-render when home summary data changes
  store.on('data.homeSummary', () => {
    const s = store.get();
    if (!s.nav.activeConversationId) renderHome();
  });
}

export async function loadHomeSummary() {
  try {
    const summary = await api('/api/home/summary');
    _store.update(s => { s.data.homeSummary = summary; });
  } catch {
    _store.update(s => { s.data.homeSummary = null; });
  }
}

export function renderHome() {
  const chatView = document.getElementById('chat-view');
  const homeView = document.getElementById('home-view');
  const dashboard = document.getElementById('home-dashboard');
  const directoryView = document.getElementById('directory-view');
  const orgDashboardView = document.getElementById('org-dashboard-view');

  if (chatView) chatView.classList.add('hidden');
  if (homeView) homeView.classList.remove('hidden');
  if (directoryView) directoryView.classList.add('hidden');
  if (orgDashboardView) orgDashboardView.classList.add('hidden');

  const s = _store.get();
  if (!s.auth.user) return;

  const authGate = document.getElementById('auth-gate');
  if (authGate) authGate.classList.add('hidden');
  if (dashboard) dashboard.classList.remove('hidden');

  const summary = s.data.homeSummary;
  if (!summary?.orgs?.length) {
    if (dashboard) dashboard.innerHTML = '';
    return;
  }

  const totalJobs = summary.total_active_jobs || 0;
  const totalAttention = summary.total_attention_needed || 0;

  const orgCards = summary.orgs.map(org => {
    const hasJobs = org.active_jobs > 0;
    const needsAttention = org.attention_needed > 0;
    const dotClass = needsAttention ? 'warning' : hasJobs ? 'active' : 'idle';

    const badges = [];
    if (org.workgroup_count > 0) {
      badges.push(`<span class="home-badge">${org.workgroup_count} workgroup${org.workgroup_count !== 1 ? 's' : ''}</span>`);
    }
    if (org.active_jobs > 0) {
      badges.push(`<span class="home-badge active">${org.active_jobs} active</span>`);
    }
    if (org.attention_needed > 0) {
      badges.push(`<span class="home-badge warning">${org.attention_needed} attention</span>`);
    }

    return `
      <button class="home-org-card" data-org-id="${escapeHtml(org.id)}">
        <div class="home-org-card-header">
          <span class="presence-dot presence-${dotClass}"></span>
          <span class="home-org-card-name">${escapeHtml(org.name)}</span>
        </div>
        <div class="home-org-card-badges">${badges.join('')}</div>
      </button>
    `;
  }).join('');

  if (dashboard) {
    dashboard.innerHTML = `
      <div class="home-header">
        <h3 class="heading-serif">Your Organizations</h3>
        ${totalJobs > 0 ? `<span class="home-badge">${totalJobs} active job${totalJobs !== 1 ? 's' : ''}</span>` : ''}
        ${totalAttention > 0 ? `<span class="home-badge warning">${totalAttention} need attention</span>` : ''}
      </div>
      <div class="home-org-grid">${orgCards}</div>
    `;

    // Wire up org card clicks
    dashboard.querySelectorAll('.home-org-card').forEach(card => {
      card.addEventListener('click', () => {
        const orgId = card.dataset.orgId;
        _store.update(s => { s.nav.activeOrgId = orgId; });
        _store.notify('nav.activeOrgId');
        bus.emit('nav:org-selected', { orgId });
      });
    });
  }
}

// Org activity rendering
const _activityCache = {};

export async function loadOrgActivity(orgId) {
  try {
    const data = await api(`/api/organizations/${orgId}/activity`);
    _activityCache[orgId] = data;
    return data;
  } catch { return []; }
}

export function renderOrgActivityHtml(orgId) {
  const items = _activityCache[orgId] || [];
  if (!items.length) return '<p class="meta">No recent activity.</p>';

  return items.slice(0, 15).map(item => {
    const time = formatRelativeTime(item.timestamp);
    return `
      <div class="activity-item" ${item.conversation_id ? `data-conversation="${escapeHtml(item.conversation_id)}"` : ''}>
        <span class="activity-summary">${escapeHtml(item.summary || '')}</span>
        <span class="activity-time meta">${escapeHtml(time)}</span>
      </div>
    `;
  }).join('');
}

function formatRelativeTime(iso) {
  const diff = Date.now() - new Date(iso).getTime();
  if (diff < 60000) return 'just now';
  if (diff < 3600000) return Math.floor(diff / 60000) + 'm ago';
  if (diff < 86400000) return Math.floor(diff / 3600000) + 'h ago';
  return Math.floor(diff / 86400000) + 'd ago';
}
