// Org dashboard: strategic overview shown when an org is selected.
// Sections: summary bar, financials graph, activity graph, engagement pipeline, owner extras.

import { api } from '../../core/api.js';
import { bus } from '../../core/bus.js';
import { escapeHtml } from '../../core/utils.js';
import { showOrgDashboardView } from '../chat/chat-panel.js';

let _store = null;
let _currentOrgId = '';

export function initOrgDashboard(store) {
  _store = store;

  bus.on('nav:org-selected', ({ orgId }) => {
    const s = store.get();
    // Don't show dashboard if we have an active conversation (e.g. restored from nav state)
    if (s.nav.activeConversationId) return;
    _currentOrgId = orgId;
    showOrgDashboardView();
    renderDashboard(orgId);
    loadDashboardData(orgId);
  });

  // Sidebar info button — always show dashboard for the active org
  bus.on('nav:org-settings', ({ orgId }) => {
    store.update(s => { s.nav.activeConversationId = ''; });
    _currentOrgId = orgId;
    showOrgDashboardView();
    renderDashboard(orgId);
    loadDashboardData(orgId);
  });

  bus.on('nav:home', () => {
    _currentOrgId = '';
  });

  // Re-render when dashboard data arrives
  store.on('data.orgDashboard', () => {
    if (_currentOrgId) renderDashboard(_currentOrgId);
  });

  // Re-render when tree data changes (live agent/job updates)
  store.on('data.treeData', () => {
    const dashboardView = document.getElementById('org-dashboard-view');
    if (_currentOrgId && dashboardView && !dashboardView.classList.contains('hidden')) {
      renderDashboard(_currentOrgId);
    }
  });
}

async function loadDashboardData(orgId) {
  const calls = [
    api(`/api/organizations/${orgId}/summary`).catch(() => null),
    api(`/api/organizations/${orgId}/spending-breakdown`).catch(() => null),
    api(`/api/organizations/${orgId}/members`).catch(() => []),
    api(`/api/organizations/${orgId}/projects`).catch(() => []),
    api(`/api/organizations/${orgId}/engagements`).catch(() => []),
    api(`/api/organizations/${orgId}/balance`).catch(() => null),
    api(`/api/organizations/${orgId}/transactions`).catch(err => {
      // 403 = not owner; gracefully return a sentinel
      if (err?.status === 403) return { forbidden: true };
      return null;
    }),
    api(`/api/organizations/${orgId}/agent-usage`).catch(() => null),
  ];

  const [summary, spendingBreakdown, members, projects, engagements, balance, transactions, agentUsage] = await Promise.all(calls);

  // Guard against stale responses
  if (_currentOrgId !== orgId) return;

  // Fetch per-workgroup LLM usage for spend breakdown
  const s = _store.get();
  const wgs = (s.data.workgroups || []).filter(w => w.organization_id === orgId);
  const usageCalls = wgs.map(wg =>
    api(`/api/workgroups/${wg.id}/usage`).catch(() => null).then(u => ({ workgroup: wg, usage: u }))
  );
  const workgroupUsage = await Promise.all(usageCalls);

  if (_currentOrgId !== orgId) return;

  _store.update(s => {
    s.data.orgDashboard = { summary, spendingBreakdown, members, projects, engagements, balance, transactions, workgroupUsage, agentUsage };
  });
  _store.notify('data.orgDashboard');
}

// ─── Main Render ──────────────────────────────────────────────────────────────

function renderDashboard(orgId) {
  const container = document.getElementById('org-dashboard-content');
  if (!container) return;

  const s = _store.get();
  const org = (s.data.organizations || []).find(o => o.id === orgId);
  if (!org) return;

  const db = s.data.orgDashboard || {};
  const isOwner = org.owner_id === s.auth.user?.id;

  const html = [
    `<h3 class="heading-serif org-dash-title">${escapeHtml(org.name)}</h3>`,
    renderSummaryBar(orgId, db),
    renderFinancialsGraph(orgId, db),
    renderSpendByWorkgroup(db),
    renderSpendByAgent(db),
    renderSpendByCategory(db),
    renderEngagementPipeline(db),
    isOwner ? renderOwnerExtras(org) : '',
  ].join('');

  container.innerHTML = html;
  wireEvents(container, orgId);
}

// ─── Summary Bar ──────────────────────────────────────────────────────────────

function renderSummaryBar(orgId, db) {
  const s = _store.get();
  const summary = db.summary;
  const wgs = (s.data.workgroups || []).filter(w => w.organization_id === orgId);

  const wgCount = summary?.workgroups?.length ?? wgs.length;
  const activeJobs = summary?.active_jobs ?? '—';
  const activeProjects = summary?.active_projects ?? '—';
  const balance = db.balance;
  const credits = balance ? formatCredits(balance.balance_credits) : '—';

  const homeSummary = s.data.homeSummary;
  const orgSummary = homeSummary?.orgs?.find(o => o.id === orgId);
  const attention = orgSummary?.attention_needed ?? 0;
  const healthClass = attention > 0 ? 'attention' : 'healthy';
  const healthLabel = attention > 0 ? `${attention} need attention` : 'All clear';

  return `
    <div class="org-dash-summary-bar">
      <div class="org-dash-stat-tile">
        <span class="org-dash-stat-value">${wgCount}</span>
        <span class="org-dash-stat-label">Workgroups</span>
      </div>
      <div class="org-dash-stat-tile">
        <span class="org-dash-stat-value">${activeJobs}</span>
        <span class="org-dash-stat-label">Active Jobs</span>
      </div>
      <div class="org-dash-stat-tile">
        <span class="org-dash-stat-value">${activeProjects}</span>
        <span class="org-dash-stat-label">Projects</span>
      </div>
      <div class="org-dash-stat-tile">
        <span class="org-dash-stat-value">${escapeHtml(credits)}</span>
        <span class="org-dash-stat-label">Credits</span>
      </div>
      <div class="org-dash-stat-tile">
        <span class="org-dash-stat-value"><span class="org-dash-health-dot ${healthClass}"></span>${escapeHtml(healthLabel)}</span>
        <span class="org-dash-stat-label">Health</span>
      </div>
    </div>
  `;
}

// ─── Financials: Balance Over Time ────────────────────────────────────────────

function renderFinancialsGraph(orgId, db) {
  const txData = db.transactions;

  // Owner access required
  if (txData?.forbidden) {
    return `
      <div class="org-dash-section">
        <div class="org-dash-section-header"><h4 class="heading-serif">Financials</h4></div>
        <p class="meta">Owner access required.</p>
      </div>
    `;
  }

  const balance = db.balance;
  const currentBalance = balance?.balance_credits ?? null;
  const transactions = Array.isArray(txData) ? txData : [];

  // Compute revenue, spend, net flow from transactions
  let revenue = 0;
  let spend = 0;
  for (const tx of transactions) {
    const amt = tx.amount_credits ?? 0;
    if (amt > 0) revenue += amt;
    else spend += Math.abs(amt);
  }
  const netFlow = revenue - spend;

  const balanceDisplay = currentBalance !== null
    ? formatCredits(currentBalance)
    : '—';

  const chartSvg = renderLineChart(transactions);

  const statTiles = `
    <div class="org-dash-fin-stats-row">
      <div class="org-dash-fin-stat">
        <span class="org-dash-fin-stat-label">Revenue</span>
        <span class="org-dash-fin-stat-value earned">${formatCredits(revenue)}</span>
      </div>
      <div class="org-dash-fin-stat">
        <span class="org-dash-fin-stat-label">Spend</span>
        <span class="org-dash-fin-stat-value spent">${formatCredits(spend)}</span>
      </div>
      <div class="org-dash-fin-stat">
        <span class="org-dash-fin-stat-label">Net Flow</span>
        <span class="org-dash-fin-stat-value ${netFlow >= 0 ? 'earned' : 'spent'}">${netFlow >= 0 ? '+' : ''}${formatCredits(netFlow)}</span>
      </div>
    </div>
  `;

  return `
    <div class="org-dash-section">
      <div class="org-dash-section-header"><h4 class="heading-serif">Financials</h4></div>
      <div class="org-dash-balance-hero">
        <span class="org-dash-balance-amount ${currentBalance !== null && currentBalance <= 0 ? 'low' : ''}">${escapeHtml(balanceDisplay)}</span>
        <span class="org-dash-balance-label">current balance</span>
      </div>
      <div class="org-dash-chart-container">
        ${chartSvg}
      </div>
      ${statTiles}
    </div>
  `;
}

function renderLineChart(transactions) {
  if (!transactions.length) {
    return `<div class="org-dash-chart-empty">No transaction history</div>`;
  }

  // Sort by date ascending
  const sorted = [...transactions].sort((a, b) => new Date(a.created_at) - new Date(b.created_at));

  // Build points array: {date, balance}
  const points = sorted.map(tx => ({
    date: new Date(tx.created_at),
    balance: tx.balance_after_credits ?? 0,
  }));

  // SVG dimensions
  const W = 600, H = 200;
  const ML = 56, MR = 12, MT = 14, MB = 34;
  const plotW = W - ML - MR;
  const plotH = H - MT - MB;

  const minDate = points[0].date.getTime();
  const maxDate = points[points.length - 1].date.getTime();
  const dateRange = maxDate - minDate || 1;

  const balances = points.map(p => p.balance);
  const minBal = Math.min(...balances);
  const maxBal = Math.max(...balances);
  const balPad = (maxBal - minBal) * 0.1 || 1;
  const balLow = minBal - balPad;
  const balHigh = maxBal + balPad;
  const balRange = balHigh - balLow;

  const toX = t => ML + ((t - minDate) / dateRange) * plotW;
  const toY = b => MT + (1 - (b - balLow) / balRange) * plotH;

  // Smooth line using cubic bezier control points
  const smoothParts = [];
  for (let i = 0; i < points.length; i++) {
    const x = toX(points[i].date.getTime());
    const y = toY(points[i].balance);
    if (i === 0) {
      smoothParts.push(`M ${x.toFixed(1)} ${y.toFixed(1)}`);
    } else {
      const px = toX(points[i - 1].date.getTime());
      const py = toY(points[i - 1].balance);
      const cpx = ((px + x) / 2).toFixed(1);
      smoothParts.push(`C ${cpx} ${py.toFixed(1)}, ${cpx} ${y.toFixed(1)}, ${x.toFixed(1)} ${y.toFixed(1)}`);
    }
  }
  const linePath = smoothParts.join(' ');

  // Area fill path (close back along x-axis)
  const firstX = toX(points[0].date.getTime()).toFixed(1);
  const lastX = toX(points[points.length - 1].date.getTime()).toFixed(1);
  const bottomY = (MT + plotH).toFixed(1);
  const areaPath = `${linePath} L ${lastX} ${bottomY} L ${firstX} ${bottomY} Z`;

  // Y-axis ticks (4 ticks)
  const yTicks = [];
  for (let i = 0; i <= 4; i++) {
    const val = balLow + (balRange * i) / 4;
    const y = toY(val).toFixed(1);
    const label = formatCredits(Math.round(val));
    yTicks.push({ y, label });
  }

  // X-axis labels (~5 evenly spaced)
  const xLabels = [];
  const labelCount = Math.min(5, points.length);
  for (let i = 0; i < labelCount; i++) {
    const idx = Math.round((i / (labelCount - 1)) * (points.length - 1));
    const p = points[Math.min(idx, points.length - 1)];
    const x = toX(p.date.getTime()).toFixed(1);
    const label = `${p.date.getMonth() + 1}/${p.date.getDate()}`;
    xLabels.push({ x, label });
  }

  const gradId = 'fin-area-grad';

  return `
    <div class="org-dash-chart-wrap">
      <svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" class="org-dash-svg" aria-hidden="true">
        <defs>
          <linearGradient id="${gradId}" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="var(--tp-primary)" stop-opacity="0.18"/>
            <stop offset="100%" stop-color="var(--tp-primary)" stop-opacity="0.02"/>
          </linearGradient>
        </defs>

        <!-- Grid lines and y-axis ticks -->
        ${yTicks.map(t => `
          <line x1="${ML}" y1="${t.y}" x2="${W - MR}" y2="${t.y}"
                stroke="var(--tp-line-subtle)" stroke-width="1"/>
          <text x="${ML - 6}" y="${t.y}" text-anchor="end" dominant-baseline="middle"
                font-size="10" fill="var(--tp-muted)" font-family="inherit">${escapeHtml(t.label)}</text>
        `).join('')}

        <!-- Axis lines -->
        <line x1="${ML}" y1="${MT}" x2="${ML}" y2="${MT + plotH}"
              stroke="var(--tp-line)" stroke-width="1"/>
        <line x1="${ML}" y1="${MT + plotH}" x2="${W - MR}" y2="${MT + plotH}"
              stroke="var(--tp-line)" stroke-width="1"/>

        <!-- Area fill -->
        <path d="${areaPath}" fill="url(#${gradId})"/>

        <!-- Line -->
        <path d="${linePath}" fill="none" stroke="var(--tp-primary)" stroke-width="2"
              stroke-linecap="round" stroke-linejoin="round"/>

        <!-- X-axis labels -->
        ${xLabels.map(l => `
          <text x="${l.x}" y="${MT + plotH + 16}" text-anchor="middle"
                font-size="10" fill="var(--tp-muted)" font-family="inherit">${escapeHtml(l.label)}</text>
        `).join('')}

        <!-- End dot -->
        <circle cx="${toX(points[points.length - 1].date.getTime()).toFixed(1)}"
                cy="${toY(points[points.length - 1].balance).toFixed(1)}"
                r="3.5" fill="var(--tp-primary)"/>
      </svg>
    </div>
  `;
}

// ─── Spend by Workgroup ─────────────────────────────────────────────────────

function renderSpendByWorkgroup(db) {
  const items = db.workgroupUsage || [];
  const withCost = items.filter(i => i.usage && i.usage.estimated_cost_usd > 0);

  if (!withCost.length) {
    return `
      <div class="org-dash-section">
        <div class="org-dash-section-header"><h4 class="heading-serif">Spend by Workgroup</h4></div>
        <div class="org-dash-chart-container">
          <div class="org-dash-chart-empty">No LLM usage recorded</div>
        </div>
      </div>
    `;
  }

  // Sort by cost descending
  withCost.sort((a, b) => b.usage.estimated_cost_usd - a.usage.estimated_cost_usd);
  const totalCost = withCost.reduce((sum, i) => sum + i.usage.estimated_cost_usd, 0);
  const totalCalls = withCost.reduce((sum, i) => sum + i.usage.api_calls, 0);

  const chartSvg = renderSpendBars(withCost);

  return `
    <div class="org-dash-section">
      <div class="org-dash-section-header"><h4 class="heading-serif">Spend by Workgroup</h4></div>
      <div class="org-dash-chart-container">
        ${chartSvg}
      </div>
      <div class="org-dash-pipeline-meta">
        <span class="meta"><strong>$${totalCost.toFixed(2)}</strong> total spend</span>
        <span class="meta"><strong>${totalCalls.toLocaleString()}</strong> API calls</span>
      </div>
    </div>
  `;
}

function renderSpendBars(items) {
  const maxCost = items[0].usage.estimated_cost_usd;

  // SVG dimensions — scale height to item count
  const W = 600;
  const rowH = 36;
  const ML = 140; // left margin for labels
  const MR = 60;  // right margin for values
  const MT = 4;
  const MB = 4;
  const plotW = W - ML - MR;
  const H = MT + items.length * rowH + MB;

  // Palette — cycle through colors for each workgroup
  const palette = [
    'var(--tp-primary)',
    'var(--tp-accent)',
    'var(--tp-success)',
    'var(--tp-warning)',
    'var(--tp-error)',
  ];

  const bars = items.map((item, i) => {
    const cost = item.usage.estimated_cost_usd;
    const name = item.workgroup.name || 'Untitled';
    const barW = Math.max(2, (cost / maxCost) * plotW);
    const y = MT + i * rowH;
    const barH = rowH * 0.6;
    const barY = y + (rowH - barH) / 2;
    const color = palette[i % palette.length];

    return `
      <g>
        <text x="${ML - 8}" y="${y + rowH / 2}" text-anchor="end" dominant-baseline="middle"
              font-size="12" fill="var(--tp-ink)" font-family="inherit"
              style="font-weight: 500">${escapeHtml(name.length > 18 ? name.slice(0, 17) + '\u2026' : name)}</text>
        <rect x="${ML}" y="${barY.toFixed(1)}" width="${barW.toFixed(1)}" height="${barH.toFixed(1)}"
              fill="${color}" opacity="0.85" rx="3"/>
        <text x="${ML + barW + 6}" y="${y + rowH / 2}" text-anchor="start" dominant-baseline="middle"
              font-size="11" fill="var(--tp-muted)" font-family="inherit"
              style="font-weight: 600">$${cost.toFixed(2)}</text>
      </g>
    `;
  }).join('');

  return `
    <div class="org-dash-chart-wrap">
      <svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" class="org-dash-svg" aria-hidden="true">
        ${bars}
      </svg>
    </div>
  `;
}

// ─── Spend by Agent ──────────────────────────────────────────────────────────

function renderSpendByAgent(db) {
  const data = db.agentUsage;
  const agents = (data?.agents || []).filter(a => a.cost_usd > 0);

  if (!agents.length) {
    return `
      <div class="org-dash-section">
        <div class="org-dash-section-header"><h4 class="heading-serif">Spend by Agent</h4></div>
        <div class="org-dash-chart-container">
          <div class="org-dash-chart-empty">No agent usage recorded</div>
        </div>
      </div>
    `;
  }

  // Map agent data into the shape renderSpendBars expects
  const items = agents.map(a => ({
    workgroup: { name: a.agent_name },
    usage: { estimated_cost_usd: a.cost_usd, api_calls: a.api_calls },
  }));

  const totalCost = agents.reduce((sum, a) => sum + a.cost_usd, 0);
  const totalCalls = agents.reduce((sum, a) => sum + a.api_calls, 0);

  const chartSvg = renderSpendBars(items);

  return `
    <div class="org-dash-section">
      <div class="org-dash-section-header"><h4 class="heading-serif">Spend by Agent</h4></div>
      <div class="org-dash-chart-container">
        ${chartSvg}
      </div>
      <div class="org-dash-pipeline-meta">
        <span class="meta"><strong>$${totalCost.toFixed(2)}</strong> total spend</span>
        <span class="meta"><strong>${totalCalls.toLocaleString()}</strong> API calls</span>
      </div>
    </div>
  `;
}

// ─── Spend by Category ─────────────────────────────────────────────────────────

function renderSpendByCategory(db) {
  const data = db.spendingBreakdown;
  const categories = data?.categories || [];
  const totalCost = data?.total_cost_usd ?? 0;
  const totalCalls = data?.total_api_calls ?? 0;

  const chartSvg = renderDonutChart(categories, totalCost);

  return `
    <div class="org-dash-section">
      <div class="org-dash-section-header"><h4 class="heading-serif">Spend by Category</h4></div>
      <div class="org-dash-chart-container">
        ${chartSvg}
      </div>
      <div class="org-dash-pipeline-meta">
        <span class="meta"><strong>$${totalCost.toFixed(2)}</strong> total spend</span>
        <span class="meta"><strong>${totalCalls.toLocaleString()}</strong> API calls</span>
      </div>
    </div>
  `;
}

function renderDonutChart(categories, totalCost) {
  const withCost = categories.filter(c => c.cost_usd > 0);
  if (!withCost.length) {
    return `<div class="org-dash-chart-empty">No LLM usage recorded</div>`;
  }

  // Color map
  const colorMap = {
    'Engagements': 'var(--tp-primary)',
    'Administration': 'var(--tp-accent)',
    'Projects': 'var(--tp-success)',
    'Other': 'var(--tp-muted)',
  };

  const W = 600, H = 200;
  const cx = 130, cy = 100, r = 70;
  const circumference = 2 * Math.PI * r;

  // Build slices
  let offset = 0;
  const slices = withCost.map(cat => {
    const fraction = totalCost > 0 ? cat.cost_usd / totalCost : 0;
    const dashLen = fraction * circumference;
    const color = colorMap[cat.category] || 'var(--tp-muted)';
    const slice = { cat, fraction, dashLen, offset, color };
    offset += dashLen;
    return slice;
  });

  const circles = slices.map(s => `
    <circle cx="${cx}" cy="${cy}" r="${r}" fill="none"
            stroke="${s.color}" stroke-width="28" opacity="0.85"
            stroke-dasharray="${s.dashLen.toFixed(2)} ${(circumference - s.dashLen).toFixed(2)}"
            stroke-dashoffset="${(-s.offset).toFixed(2)}"
            transform="rotate(-90 ${cx} ${cy})"/>
  `).join('');

  // Center label
  const centerLabel = `
    <text x="${cx}" y="${cy - 8}" text-anchor="middle" dominant-baseline="middle"
          font-size="18" font-weight="700" fill="var(--tp-ink)" font-family="inherit">$${totalCost.toFixed(2)}</text>
    <text x="${cx}" y="${cy + 12}" text-anchor="middle" dominant-baseline="middle"
          font-size="11" fill="var(--tp-muted)" font-family="inherit">total</text>
  `;

  // Legend on the right
  const legendX = 280;
  const legendStartY = 40;
  const legendRowH = 36;

  const legendItems = withCost.map((cat, i) => {
    const color = colorMap[cat.category] || 'var(--tp-muted)';
    const pct = totalCost > 0 ? ((cat.cost_usd / totalCost) * 100).toFixed(1) : '0.0';
    const y = legendStartY + i * legendRowH;
    return `
      <g transform="translate(${legendX}, ${y})">
        <rect x="0" y="0" width="10" height="10" rx="2" fill="${color}" opacity="0.85"/>
        <text x="16" y="9" font-size="12" font-weight="600" fill="var(--tp-ink)" font-family="inherit">${escapeHtml(cat.category)}</text>
        <text x="16" y="24" font-size="11" fill="var(--tp-muted)" font-family="inherit">$${cat.cost_usd.toFixed(2)} (${pct}%)</text>
      </g>
    `;
  }).join('');

  return `
    <div class="org-dash-chart-wrap">
      <svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" class="org-dash-svg" aria-hidden="true">
        ${circles}
        ${centerLabel}
        ${legendItems}
      </svg>
    </div>
  `;
}

// ─── Engagement Pipeline ────────────────────────────────────────────────────

function renderEngagementPipeline(db) {
  const s = _store.get();
  const partnerships = s.data.partnerships || [];
  const engagements = db.engagements || [];

  const pipeline = { proposed: 0, negotiating: 0, in_progress: 0, completed: 0 };
  let totalValue = 0;

  for (const eng of engagements) {
    const price = eng.agreed_price_credits || 0;
    if (price) totalValue += price;

    if (eng.status === 'proposed') pipeline.proposed++;
    else if (eng.status === 'accepted' || eng.status === 'negotiating') pipeline.negotiating++;
    else if (eng.status === 'in_progress') pipeline.in_progress++;
    else if (eng.status === 'completed' || eng.status === 'reviewed') pipeline.completed++;
  }

  const partnerCount = partnerships.filter(p => p.status === 'accepted').length;
  const total = pipeline.proposed + pipeline.negotiating + pipeline.in_progress + pipeline.completed;

  const barSvg = renderPipelineBar(pipeline, total);

  const metaRow = `
    <div class="org-dash-pipeline-meta">
      <span class="meta"><strong>${partnerCount}</strong> partner${partnerCount !== 1 ? 's' : ''}</span>
      <span class="meta"><strong>${total}</strong> engagement${total !== 1 ? 's' : ''}</span>
      ${totalValue > 0 ? `<span class="meta"><strong>${formatCredits(totalValue)}</strong> total value</span>` : ''}
    </div>
  `;

  return `
    <div class="org-dash-section">
      <div class="org-dash-section-header"><h4 class="heading-serif">Engagement Pipeline</h4></div>
      <div class="org-dash-chart-container">
        ${barSvg}
      </div>
      ${metaRow}
    </div>
  `;
}

function renderPipelineBar(pipeline, total) {
  if (total === 0) {
    return `<div class="org-dash-chart-empty">No engagements yet</div>`;
  }

  const W = 600, H = 52;
  const ML = 0, MR = 0, barH = 32, barY = 10;

  const segments = [
    { key: 'proposed',    label: 'Proposed',    count: pipeline.proposed,    color: 'var(--tp-muted)' },
    { key: 'negotiating', label: 'Negotiating', count: pipeline.negotiating, color: 'var(--tp-accent)' },
    { key: 'in_progress', label: 'In Progress', count: pipeline.in_progress, color: 'var(--tp-primary)' },
    { key: 'completed',   label: 'Completed',   count: pipeline.completed,   color: 'var(--tp-success)' },
  ].filter(s => s.count > 0);

  let xCursor = 0;
  const rects = [];
  const labels = [];
  const MIN_LABEL_W = 40;

  for (let i = 0; i < segments.length; i++) {
    const seg = segments[i];
    const segW = (seg.count / total) * W;
    const rx = i === 0 ? 6 : 0;
    const rxRight = i === segments.length - 1 ? 6 : 0;

    // Build rounded rect path manually for left/right independent radii
    const x = xCursor;
    const y = barY;
    const w = segW;
    const h = barH;
    const rTL = rx, rTR = rxRight, rBR = rxRight, rBL = rx;

    const pathD = [
      `M ${(x + rTL).toFixed(1)} ${y}`,
      `H ${(x + w - rTR).toFixed(1)}`,
      rTR ? `Q ${(x + w).toFixed(1)} ${y} ${(x + w).toFixed(1)} ${(y + rTR).toFixed(1)}` : '',
      `V ${(y + h - rBR).toFixed(1)}`,
      rBR ? `Q ${(x + w).toFixed(1)} ${(y + h).toFixed(1)} ${(x + w - rBR).toFixed(1)} ${(y + h).toFixed(1)}` : '',
      `H ${(x + rBL).toFixed(1)}`,
      rBL ? `Q ${x} ${(y + h).toFixed(1)} ${x} ${(y + h - rBL).toFixed(1)}` : '',
      `V ${(y + rTL).toFixed(1)}`,
      rTL ? `Q ${x} ${y} ${(x + rTL).toFixed(1)} ${y}` : '',
      'Z',
    ].filter(Boolean).join(' ');

    rects.push(`<path d="${pathD}" fill="${seg.color}" opacity="0.9"/>`);

    // Label inside segment if wide enough
    if (segW >= MIN_LABEL_W) {
      const cx = (xCursor + segW / 2).toFixed(1);
      const cy = (barY + barH / 2).toFixed(1);
      labels.push(`
        <text x="${cx}" y="${cy}" text-anchor="middle" dominant-baseline="middle"
              font-size="11" font-weight="600" fill="white" font-family="inherit"
              style="text-shadow: 0 1px 2px rgba(0,0,0,0.3)">${seg.count}</text>
      `);
    }

    xCursor += segW;
  }

  // Legend below bar
  const legendItems = segments.map((seg, i) => {
    const lx = (i * 130).toFixed(1);
    return `
      <g transform="translate(${lx}, 0)">
        <rect x="0" y="0" width="8" height="8" rx="1" fill="${seg.color}" opacity="0.9"/>
        <text x="12" y="7" font-size="10" fill="var(--tp-muted)" font-family="inherit">${seg.label} (${seg.count})</text>
      </g>
    `;
  }).join('');

  const legendH = 20;
  const totalH = H + legendH;

  return `
    <div class="org-dash-chart-wrap">
      <svg viewBox="0 0 ${W} ${totalH}" xmlns="http://www.w3.org/2000/svg" class="org-dash-svg" aria-hidden="true">
        ${rects.join('')}
        ${labels.join('')}
        <g transform="translate(0, ${H})">
          ${legendItems}
        </g>
      </svg>
    </div>
  `;
}

// ─── Owner Extras ─────────────────────────────────────────────────────────────

function renderOwnerExtras(org) {
  const accepting = org.is_accepting_engagements;
  const desc = org.service_description || '';

  return `
    <div class="org-dash-owner-section">
      <h4 class="heading-serif">Owner Tools</h4>
      <button class="btn btn-ghost org-dash-admin-btn" data-action="open-admin">Open Admin Conversation</button>
      <div class="org-dash-toggle-row">
        <span>Accepting engagements</span>
        <span class="home-badge ${accepting ? 'active' : ''}">${accepting ? 'Yes' : 'No'}</span>
      </div>
      ${desc ? `<div class="org-dash-toggle-row"><span class="meta">Service: ${escapeHtml(desc.length > 80 ? desc.slice(0, 80) + '...' : desc)}</span></div>` : ''}
    </div>
  `;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatCredits(n) {
  if (n === 0) return '0';
  return n.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 2 });
}

function formatRelativeTime(iso) {
  const diff = Date.now() - new Date(iso).getTime();
  if (diff < 60000) return 'just now';
  if (diff < 3600000) return Math.floor(diff / 60000) + 'm ago';
  if (diff < 86400000) return Math.floor(diff / 3600000) + 'h ago';
  return Math.floor(diff / 86400000) + 'd ago';
}

// ─── Event Wiring ─────────────────────────────────────────────────────────────

function wireEvents(container, orgId) {
  // Collapsible toggles
  container.querySelectorAll('.org-dash-collapse-toggle').forEach(toggle => {
    toggle.addEventListener('click', () => {
      const target = toggle.dataset.toggle;
      const content = container.querySelector(`[data-collapsible="${target}"]`);
      if (!content) return;
      const expanded = toggle.getAttribute('aria-expanded') === 'true';
      toggle.setAttribute('aria-expanded', String(!expanded));
      content.classList.toggle('hidden', expanded);
    });
  });

  // Admin conversation button
  const adminBtn = container.querySelector('.org-dash-admin-btn');
  if (adminBtn) {
    adminBtn.addEventListener('click', async () => {
      try {
        const result = await api(`/api/organizations/${orgId}/admin-conversation`, { method: 'POST' });
        if (result.conversation_id && result.workgroup_id) {
          bus.emit('nav:conversation-selected', {
            workgroupId: result.workgroup_id,
            conversationId: result.conversation_id,
          });
        }
      } catch (err) {
        console.error('Failed to open admin conversation:', err);
      }
    });
  }
}
