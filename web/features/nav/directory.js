// Directory: inline view for browsing organizations and people.
// Renders inside #directory-view in main-content, with People/Organizations tabs and search.

import { bus } from '../../core/bus.js';
import { api } from '../../core/api.js';
import { escapeHtml } from '../../core/utils.js';

let _store = null;
let _activeTab = 'people'; // 'people' | 'orgs'
let _orgs = [];
let _users = [];
let _cacheTime = 0;

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
  } catch {
    // keep stale data
  }
}

async function showDirectoryView() {
  const directoryView = document.getElementById('directory-view');
  const chatView = document.getElementById('chat-view');
  const homeView = document.getElementById('home-view');
  const profileView = document.getElementById('agent-profile-view');

  if (directoryView) directoryView.classList.remove('hidden');
  if (chatView) chatView.classList.add('hidden');
  if (homeView) homeView.classList.add('hidden');
  if (profileView) profileView.classList.add('hidden');
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

function buildResults(query) {
  const q = (query || '').toLowerCase();
  const results = [];

  if (_activeTab === 'orgs') {
    for (const org of _orgs) {
      if (!q || org.name.toLowerCase().includes(q) || (org.description || '').toLowerCase().includes(q)) {
        results.push({
          type: 'org', id: org.id, label: org.name,
          sublabel: org.service_description || org.description || '',
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

  if (!results.length) {
    container.innerHTML = '<p class="qs-empty">No results</p>';
    return;
  }

  let html = '<div class="directory-grid">';
  for (const item of results) {
    const avatar = item.type === 'person' && item.picture
      ? `<img src="${escapeHtml(item.picture)}" class="dir-card-avatar" alt="" />`
      : `<span class="dir-card-icon">${typeIcon(item.type)}</span>`;

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

    html += `<button class="dir-card" data-type="${item.type}" data-id="${escapeHtml(item.id)}">
      ${avatar}
      <span class="dir-card-name">${escapeHtml(item.label)}</span>
      <span class="dir-card-detail">${escapeHtml(item.sublabel)}</span>
      ${meta}
    </button>`;
  }
  html += '</div>';

  container.innerHTML = html;

  container.querySelectorAll('.dir-card').forEach(btn => {
    btn.addEventListener('click', () => {
      activateResult(btn.dataset.type, btn.dataset.id);
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
