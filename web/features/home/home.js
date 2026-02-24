// Home dashboard: rolled-up org dashboards, activity feed, welcome state.

import { api } from '../../core/api.js';
import { bus } from '../../core/bus.js';
import { escapeHtml } from '../../core/utils.js';
import {
  loadDashboardDataForOrg,
  renderSummaryBar,
  renderFinancialsGraph,
  renderSpendByAgent,
  renderSpendByCategory,
  renderEngagementPipeline,
} from '../dashboard/org-dashboard.js';

let _store = null;

export function initHome(store) {
  _store = store;

  bus.on('nav:home', () => {
    renderHome();
    loadHomeDashboards();
  });

  // Load dashboards when orgs data arrives (covers initial boot)
  store.on('data.organizations', () => {
    const homeView = document.getElementById('home-view');
    if (!homeView || homeView.classList.contains('hidden')) return;
    loadHomeDashboards();
  });

  store.on('data.homeDashboards', () => {
    const homeView = document.getElementById('home-view');
    if (!homeView || homeView.classList.contains('hidden')) return;
    renderHome();
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

export async function loadHomeDashboards() {
  const s = _store.get();
  const orgs = s.data.organizations || [];
  if (!orgs.length) return;

  const results = await Promise.all(
    orgs.map(async org => {
      const db = await loadDashboardDataForOrg(org.id);
      return { orgId: org.id, db };
    })
  );

  const dashboards = {};
  for (const { orgId, db } of results) {
    dashboards[orgId] = db;
  }

  _store.update(s => { s.data.homeDashboards = dashboards; });
  _store.notify('data.homeDashboards');
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

  const orgs = s.data.organizations || [];
  if (!orgs.length) {
    if (dashboard) dashboard.innerHTML = '';
    return;
  }

  const dashboards = s.data.homeDashboards || {};

  const orgSections = orgs.map(org => {
    const db = dashboards[org.id] || {};
    return `
      <div class="home-org-dashboard">
        <button class="home-org-dashboard-header" data-org-id="${escapeHtml(org.id)}">
          <h3 class="heading-serif">${escapeHtml(org.name)}</h3>
        </button>
        ${renderSummaryBar(org.id, db)}
        ${renderFinancialsGraph(org.id, db)}
        ${renderSpendByAgent(db)}
        ${renderSpendByCategory(db)}
        ${renderEngagementPipeline(db)}
      </div>
    `;
  }).join('');

  const rollupHtml = renderSpendByOrganization(orgs, dashboards);

  if (dashboard) {
    dashboard.innerHTML = rollupHtml + orgSections;

    dashboard.querySelectorAll('.home-org-dashboard-header').forEach(btn => {
      btn.addEventListener('click', () => {
        const orgId = btn.dataset.orgId;
        _store.update(s => { s.nav.activeOrgId = orgId; });
        _store.notify('nav.activeOrgId');
        bus.emit('nav:org-selected', { orgId });
      });
    });
  }
}

// ─── Spend by Organization (rollup) ──────────────────────────────────────────

function renderSpendByOrganization(orgs, dashboards) {
  const items = orgs.map(org => {
    const db = dashboards[org.id] || {};
    const totalCost = db.spendingBreakdown?.total_cost_usd ?? 0;
    const totalCalls = db.spendingBreakdown?.total_api_calls ?? 0;
    return { name: org.name, cost: totalCost, calls: totalCalls };
  }).filter(i => i.cost > 0);

  if (!items.length) {
    return `
      <div class="org-dash-section home-rollup-section">
        <div class="org-dash-section-header"><h4 class="heading-serif">Spend by Organization</h4></div>
        <div class="org-dash-chart-container">
          <div class="org-dash-chart-empty">No LLM usage recorded</div>
        </div>
      </div>
    `;
  }

  items.sort((a, b) => b.cost - a.cost);
  const totalCost = items.reduce((sum, i) => sum + i.cost, 0);
  const totalCalls = items.reduce((sum, i) => sum + i.calls, 0);
  const maxCost = items[0].cost;

  const palette = [
    'var(--tp-primary)',
    'var(--tp-accent)',
    'var(--tp-success)',
    'var(--tp-warning)',
    'var(--tp-error)',
  ];

  const W = 600;
  const rowH = 36;
  const ML = 140, MR = 60, MT = 4, MB = 4;
  const plotW = W - ML - MR;
  const H = MT + items.length * rowH + MB;

  const bars = items.map((item, i) => {
    const barW = Math.max(2, (item.cost / maxCost) * plotW);
    const y = MT + i * rowH;
    const barH = rowH * 0.6;
    const barY = y + (rowH - barH) / 2;
    const color = palette[i % palette.length];
    const label = item.name.length > 18 ? item.name.slice(0, 17) + '\u2026' : item.name;

    return `
      <g>
        <text x="${ML - 8}" y="${y + rowH / 2}" text-anchor="end" dominant-baseline="middle"
              font-size="12" fill="var(--tp-ink)" font-family="inherit"
              style="font-weight: 500">${escapeHtml(label)}</text>
        <rect x="${ML}" y="${barY.toFixed(1)}" width="${barW.toFixed(1)}" height="${barH.toFixed(1)}"
              fill="${color}" opacity="0.85" rx="3"/>
        <text x="${ML + barW + 6}" y="${y + rowH / 2}" text-anchor="start" dominant-baseline="middle"
              font-size="11" fill="var(--tp-muted)" font-family="inherit"
              style="font-weight: 600">$${item.cost.toFixed(2)}</text>
      </g>
    `;
  }).join('');

  return `
    <div class="org-dash-section home-rollup-section">
      <div class="org-dash-section-header"><h4 class="heading-serif">Spend by Organization</h4></div>
      <div class="org-dash-chart-container">
        <div class="org-dash-chart-wrap">
          <svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" class="org-dash-svg" aria-hidden="true">
            ${bars}
          </svg>
        </div>
      </div>
      <div class="org-dash-pipeline-meta">
        <span class="meta"><strong>$${totalCost.toFixed(2)}</strong> total spend</span>
        <span class="meta"><strong>${totalCalls.toLocaleString()}</strong> API calls</span>
      </div>
    </div>
  `;
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
