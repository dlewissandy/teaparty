// Partner profile view: displays a partner org profile with engagement history,
// financial summary, and pricing. Fetches profile, engagements, and transactions
// in parallel for a comprehensive relationship overview.

import { bus } from '../../core/bus.js';
import { api } from '../../core/api.js';
import { escapeHtml } from '../../core/utils.js';
import { avatarColor, initialsFromName } from '../../components/shared/avatar.js';
import { flash } from '../../components/shared/flash.js';

let _store = null;
let _currentPartnershipId = '';
let _currentPartnerOrgId = '';

function showPartnerProfile() {
  const views = [
    'chat-view', 'home-view', 'agent-profile-view', 'workgroup-profile-view',
    'directory-view', 'org-dashboard-view', 'org-settings-view', 'create-project-form',
  ];
  for (const id of views) { document.getElementById(id)?.classList.add('hidden'); }
  document.getElementById('partner-profile-view')?.classList.remove('hidden');

  if (_store) {
    const s = _store.get();
    if (s.panels.rightPanelOpen) {
      _store.update(st => { st.panels.rightPanelOpen = false; });
      _store.notify('panels.rightPanelOpen');
    }
  }
}

function hidePartnerProfile() {
  const profileView = document.getElementById('partner-profile-view');
  if (profileView) profileView.classList.add('hidden');
  _currentPartnershipId = '';
  _currentPartnerOrgId = '';
}

// ─── Helpers ───────────────────────────────────────────────────────────────────

function formatCredits(n) {
  if (n === 0) return '0';
  return n.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 2 });
}

function relativeDate(iso) {
  const d = new Date(iso);
  const now = new Date();
  const days = Math.floor((now - d) / 86400000);
  if (days === 0) return 'Today';
  if (days === 1) return 'Yesterday';
  if (days < 30) return `${days}d ago`;
  if (days < 365) return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

const STATUS_STYLES = {
  proposed:    { label: 'Proposed',    cls: 'muted' },
  negotiating: { label: 'Negotiating', cls: 'accent' },
  accepted:    { label: 'Accepted',    cls: 'accent' },
  in_progress: { label: 'In Progress', cls: 'primary' },
  completed:   { label: 'Completed',   cls: 'success' },
  reviewed:    { label: 'Reviewed',    cls: 'success' },
  declined:    { label: 'Declined',    cls: 'error' },
  cancelled:   { label: 'Cancelled',   cls: 'muted' },
};

function statusBadge(status) {
  const s = STATUS_STYLES[status] || { label: status, cls: 'muted' };
  return `<span class="pp-badge pp-badge--${s.cls}">${escapeHtml(s.label)}</span>`;
}

function ratingDot(rating) {
  if (!rating) return '';
  const cls = rating === 'satisfied' ? 'pp-dot--success' : 'pp-dot--error';
  const label = rating === 'satisfied' ? 'Satisfied' : 'Dissatisfied';
  return `<span class="pp-dot ${cls}" title="${label}"></span>`;
}

function txnBadgeCls(type) {
  if (type === 'credit' || type === 'escrow') return 'pp-badge pp-badge--primary';
  if (type === 'release') return 'pp-badge pp-badge--success';
  if (type === 'refund') return 'pp-badge pp-badge--error';
  return 'pp-badge pp-badge--muted';
}

// ─── Sections ──────────────────────────────────────────────────────────────────

function renderStats(summary, transactions) {
  const { total, completed, reviewed, satisfied, total_spend_credits, total_earned_credits } = summary;
  const satPct = reviewed > 0 ? Math.round((satisfied / reviewed) * 100) : null;
  const netFlow = total_earned_credits - total_spend_credits;

  const stats = [
    { value: String(total), label: 'Engagements', cls: '' },
    { value: String(completed), label: 'Completed', cls: completed > 0 ? 'pp-stat-value--success' : '' },
    {
      value: satPct !== null ? `${satPct}%` : '—',
      label: 'Satisfaction',
      cls: satPct !== null ? (satPct >= 70 ? 'pp-stat-value--success' : satPct >= 40 ? 'pp-stat-value--accent' : 'pp-stat-value--error') : '',
    },
    {
      value: (netFlow >= 0 ? '+' : '') + formatCredits(netFlow),
      label: 'Net Flow',
      cls: netFlow > 0 ? 'pp-stat-value--success' : netFlow < 0 ? 'pp-stat-value--error' : '',
    },
  ];

  return `<div class="pp-stats">${stats.map(s =>
    `<div class="pp-stat">
      <span class="pp-stat-value ${s.cls}">${s.value}</span>
      <span class="pp-stat-label">${s.label}</span>
    </div>`
  ).join('')}</div>`;
}

function renderEngagements(summary) {
  const { engagements } = summary;
  if (!engagements.length) {
    return `<div class="pp-card">
      <div class="pp-card-head"><h4>Engagement History</h4></div>
      <p class="pp-empty">No engagements with this partner yet.</p>
    </div>`;
  }

  const rows = engagements.map(eng => {
    const price = eng.agreed_price_credits
      ? `<span class="pp-eng-price">${formatCredits(eng.agreed_price_credits)}</span>`
      : '';
    const arrow = eng.direction === 'outbound' ? '&#8599;' : '&#8601;';
    const dirLabel = eng.direction === 'outbound' ? 'You hired them' : 'They hired you';
    return `<div class="pp-eng-row">
      <div class="pp-eng-left">
        <span class="pp-eng-dir" title="${dirLabel}">${arrow}</span>
        <div class="pp-eng-info">
          <span class="pp-eng-title">${escapeHtml(eng.title)}</span>
          <span class="pp-eng-date">${relativeDate(eng.created_at)}</span>
        </div>
      </div>
      <div class="pp-eng-right">
        ${ratingDot(eng.review_rating)}
        ${statusBadge(eng.status)}
        ${price}
      </div>
    </div>`;
  }).join('');

  return `<div class="pp-card">
    <div class="pp-card-head"><h4>Engagement History</h4></div>
    <div class="pp-eng-list">${rows}</div>
  </div>`;
}

function renderAboutAndPricing(org) {
  const baseFee = org.engagement_base_fee ?? 0;
  const markupPct = org.engagement_markup_pct ?? 5;
  const multiplier = (1 + markupPct / 100).toFixed(4);
  const isAccepting = org.is_accepting_engagements || false;

  const aboutHtml = org.service_description
    ? `<p class="pp-about-text">${escapeHtml(org.service_description)}</p>`
    : '';

  return `<div class="pp-card">
    <div class="pp-card-head">
      <h4>About &amp; Pricing</h4>
      ${isAccepting
        ? '<span class="pp-badge pp-badge--success">Accepting engagements</span>'
        : '<span class="pp-badge pp-badge--muted">Not accepting</span>'}
    </div>
    ${aboutHtml}
    <div class="pp-pricing">
      <div class="pp-pricing-item">
        <span class="pp-pricing-val">${escapeHtml(String(baseFee))}</span>
        <span class="pp-pricing-lbl">Base fee</span>
      </div>
      <div class="pp-pricing-item">
        <span class="pp-pricing-val">${escapeHtml(String(markupPct))}%</span>
        <span class="pp-pricing-lbl">Token markup</span>
      </div>
      <div class="pp-pricing-formula">
        <span class="pp-pricing-formula-lbl">Price</span>
        <span class="pp-pricing-formula-val">${escapeHtml(String(baseFee))} + tokens &times; ${escapeHtml(multiplier)}</span>
      </div>
    </div>
  </div>`;
}

function renderTransactions(transactions) {
  if (!transactions.length) return '';

  const rows = transactions.map(t => {
    const date = relativeDate(t.created_at);
    const isPositive = t.amount_credits >= 0;
    const cls = isPositive ? 'pp-txn-positive' : 'pp-txn-negative';
    const sign = isPositive ? '+' : '';
    return `<tr class="pp-txn-row">
      <td class="pp-txn-date">${escapeHtml(date)}</td>
      <td><span class="${txnBadgeCls(t.transaction_type)}">${escapeHtml(t.transaction_type)}</span></td>
      <td class="pp-txn-desc">${escapeHtml(t.description || '—')}</td>
      <td class="pp-txn-amount ${cls}">${sign}${formatCredits(t.amount_credits)}</td>
    </tr>`;
  }).join('');

  return `<div class="pp-card">
    <div class="pp-card-head"><h4>Transactions</h4></div>
    <table class="pp-txn-table">
      <thead><tr><th>When</th><th>Type</th><th>Description</th><th>Amount</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  </div>`;
}

// ─── Main render ───────────────────────────────────────────────────────────────

function renderProfile(org, summary, transactions) {
  const avatarEl = document.getElementById('partner-profile-avatar');
  const nameEl = document.getElementById('partner-profile-name');
  const subtitleEl = document.getElementById('partner-profile-subtitle');
  const bodyEl = document.getElementById('partner-profile-body');

  if (avatarEl) {
    if (org.icon_url) {
      avatarEl.innerHTML = `<img src="${escapeHtml(org.icon_url)}" alt="" class="partner-profile-avatar-img" />`;
    } else {
      const color = avatarColor(org.name);
      const initials = initialsFromName(org.name);
      avatarEl.innerHTML = `<span class="partner-profile-avatar-initials" style="background:${escapeHtml(color)}">${escapeHtml(initials)}</span>`;
    }
  }

  if (nameEl) nameEl.textContent = org.name;
  if (subtitleEl) subtitleEl.textContent = org.description || '';
  if (!bodyEl) return;

  bodyEl.innerHTML = [
    renderStats(summary, transactions),
    renderEngagements(summary),
    renderAboutAndPricing(org),
    renderTransactions(transactions),
  ].join('');
}

// ─── Init ──────────────────────────────────────────────────────────────────────

export function initPartnerProfile(store) {
  _store = store;

  bus.on('nav:org-selected', () => hidePartnerProfile());
  bus.on('nav:home', () => hidePartnerProfile());

  bus.on('nav:partner-selected', async ({ partnershipId, partnerOrgId }) => {
    _currentPartnershipId = partnershipId;
    _currentPartnerOrgId = partnerOrgId;

    store.update(st => { st.nav.activeConversationId = ''; });
    store.notify('nav.activeConversationId');

    try {
      const [org, summary, transactions] = await Promise.all([
        api(`/api/organizations/${partnerOrgId}/partner-profile`),
        api(`/api/organizations/${partnerOrgId}/partner-engagements`).catch(() => ({
          total: 0, completed: 0, reviewed: 0, satisfied: 0,
          total_spend_credits: 0, total_earned_credits: 0, engagements: [],
        })),
        api(`/api/organizations/${partnerOrgId}/partner-transactions`).catch(() => []),
      ]);
      if (_currentPartnerOrgId !== partnerOrgId) return;
      renderProfile(org, summary, transactions);
      showPartnerProfile();
    } catch (e) {
      flash(e.message || 'Failed to load partner profile', 'error');
    }
  });
}
