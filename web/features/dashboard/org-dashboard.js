// Org dashboard: strategic overview shown when an org is selected.
// Sections: summary bar, projects, workgroup health, financials, team, activity, engagements, owner extras.

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
    api(`/api/organizations/${orgId}/activity`).catch(() => []),
    api(`/api/organizations/${orgId}/members`).catch(() => []),
    api(`/api/organizations/${orgId}/projects`).catch(() => []),
    api(`/api/organizations/${orgId}/engagements`).catch(() => []),
    api(`/api/organizations/${orgId}/balance`).catch(() => null),
  ];

  const [summary, activity, members, projects, engagements, balance] = await Promise.all(calls);

  // Guard against stale responses
  if (_currentOrgId !== orgId) return;

  _store.update(s => {
    s.data.orgDashboard = { summary, activity, members, projects, engagements, balance };
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
    renderProjectsSection(db),
    renderWorkgroupHealth(orgId, db),
    renderFinancialsSection(orgId, db),
    renderTeamSection(db),
    renderActivityFeed(db),
    renderEngagementsSection(orgId, db),
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
  const memberCount = summary?.member_count ?? '—';
  const activeJobs = summary?.active_jobs ?? '—';
  const activeProjects = summary?.active_projects ?? '—';
  const balance = db.balance;
  const credits = balance ? formatCredits(balance.balance_credits) : '—';

  // Health: check attention from homeSummary
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
        <span class="org-dash-stat-value">${memberCount}</span>
        <span class="org-dash-stat-label">Members</span>
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

// ─── Projects ─────────────────────────────────────────────────────────────────

function renderProjectsSection(db) {
  const projects = db.projects || [];
  const active = projects.filter(p => p.status === 'in_progress' || p.status === 'pending');
  const completed = projects.filter(p => p.status === 'completed').slice(0, 5);

  let rows = '';
  if (!active.length && !completed.length) {
    rows = '<p class="meta">No projects yet.</p>';
  } else {
    rows = active.map(p => renderProjectRow(p)).join('');
    if (completed.length) {
      rows += `
        <button class="org-dash-collapse-toggle" aria-expanded="false" data-toggle="completed-projects">
          <svg class="org-dash-collapse-chevron" viewBox="0 0 20 20" fill="none" width="12" height="12">
            <path d="M5 7.5l5 5 5-5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
          <span class="meta">${completed.length} recently completed</span>
        </button>
        <div class="org-dash-collapsible hidden" data-collapsible="completed-projects">
          ${completed.map(p => renderProjectRow(p)).join('')}
        </div>
      `;
    }
  }

  return `
    <div class="org-dash-section">
      <div class="org-dash-section-header">
        <h4 class="heading-serif">Projects</h4>
      </div>
      ${rows}
    </div>
  `;
}

function renderProjectRow(p) {
  const statusClass = p.status === 'completed' ? 'completed' :
                      p.status === 'cancelled' ? 'cancelled' :
                      p.status === 'in_progress' ? 'active' : 'pending';
  const statusLabel = p.status.replace('_', ' ');

  let budgetHtml = '';
  if (p.max_cost_usd) {
    budgetHtml = `<span class="meta">$${p.max_cost_usd.toFixed(2)} budget</span>`;
  }

  return `
    <div class="org-dash-project-row">
      <span class="org-dash-project-name" title="${escapeHtml(p.name || p.prompt || 'Untitled')}">${escapeHtml(p.name || p.prompt?.slice(0, 60) || 'Untitled')}</span>
      <span class="home-badge ${statusClass}">${escapeHtml(statusLabel)}</span>
      ${budgetHtml}
    </div>
  `;
}

// ─── Workgroup Health ─────────────────────────────────────────────────────────

function renderWorkgroupHealth(orgId, db) {
  const s = _store.get();
  const wgs = (s.data.workgroups || []).filter(w => w.organization_id === orgId);
  const summaryWgs = db.summary?.workgroups || [];

  if (!wgs.length) {
    return `
      <div class="org-dash-section">
        <div class="org-dash-section-header"><h4 class="heading-serif">Workgroup Health</h4></div>
        <p class="meta">No workgroups yet.</p>
      </div>
    `;
  }

  const cards = wgs.map(wg => {
    const sw = summaryWgs.find(s => s.id === wg.id);
    const tree = s.data.treeData[wg.id];
    const agentCount = sw?.agent_count ?? tree?.agents?.length ?? 0;
    const activeJobs = sw?.active_job_count ?? 0;
    const totalJobs = sw?.job_count ?? tree?.jobRecords?.length ?? 0;
    const busy = activeJobs > 0;
    const dotClass = busy ? 'active' : 'idle';

    return `
      <button class="org-dash-wg-card" data-workgroup-id="${escapeHtml(wg.id)}">
        <div class="org-dash-wg-card-header">
          <span class="presence-dot presence-${dotClass}"></span>
          <span class="org-dash-wg-card-name">${escapeHtml(wg.name)}</span>
        </div>
        <div class="org-dash-wg-card-stats">
          <span class="home-badge">${agentCount} agent${agentCount !== 1 ? 's' : ''}</span>
          ${activeJobs > 0 ? `<span class="home-badge active">${activeJobs} active</span>` : ''}
          <span class="home-badge">${totalJobs} job${totalJobs !== 1 ? 's' : ''}</span>
        </div>
      </button>
    `;
  }).join('');

  return `
    <div class="org-dash-section">
      <div class="org-dash-section-header"><h4 class="heading-serif">Workgroup Health</h4></div>
      <div class="org-dash-wg-grid">${cards}</div>
    </div>
  `;
}

// ─── Financials ───────────────────────────────────────────────────────────────

function renderFinancialsSection(orgId, db) {
  const s = _store.get();
  const balance = db.balance;
  const engagements = db.engagements || [];
  const wgs = (s.data.workgroups || []).filter(w => w.organization_id === orgId);
  const wgIds = new Set(wgs.map(w => w.id));

  // Revenue: engagements where this org is the target (service provider)
  const revenue = { earned: 0, pipeline: 0 };
  const spend = { paid: 0, pipeline: 0 };

  for (const eng of engagements) {
    const price = eng.agreed_price_credits || 0;
    if (!price) continue;

    const isTarget = wgIds.has(eng.target_workgroup?.id);
    const isSource = wgIds.has(eng.source_workgroup?.id);

    if (isTarget) {
      if (eng.payment_status === 'paid') revenue.earned += price;
      else if (eng.payment_status === 'escrowed') revenue.pipeline += price;
    }
    if (isSource) {
      if (eng.payment_status === 'paid') spend.paid += price;
      else if (eng.payment_status === 'escrowed') spend.pipeline += price;
    }
  }

  const balanceCredits = balance ? balance.balance_credits : null;

  return `
    <div class="org-dash-section">
      <div class="org-dash-section-header"><h4 class="heading-serif">Financials</h4></div>
      <div class="org-dash-financials-grid">
        <div class="org-dash-fin-card">
          <span class="org-dash-fin-label">Balance</span>
          <span class="org-dash-fin-value ${balanceCredits !== null && balanceCredits <= 0 ? 'low' : ''}">${balanceCredits !== null ? formatCredits(balanceCredits) : '—'}</span>
        </div>
        <div class="org-dash-fin-card">
          <span class="org-dash-fin-label">Revenue Earned</span>
          <span class="org-dash-fin-value earned">${formatCredits(revenue.earned)}</span>
          ${revenue.pipeline > 0 ? `<span class="meta">+${formatCredits(revenue.pipeline)} in escrow</span>` : ''}
        </div>
        <div class="org-dash-fin-card">
          <span class="org-dash-fin-label">Spend</span>
          <span class="org-dash-fin-value spent">${formatCredits(spend.paid)}</span>
          ${spend.pipeline > 0 ? `<span class="meta">+${formatCredits(spend.pipeline)} escrowed</span>` : ''}
        </div>
        <div class="org-dash-fin-card">
          <span class="org-dash-fin-label">Net Flow</span>
          <span class="org-dash-fin-value ${revenue.earned - spend.paid >= 0 ? 'earned' : 'spent'}">${revenue.earned - spend.paid >= 0 ? '+' : ''}${formatCredits(revenue.earned - spend.paid)}</span>
        </div>
      </div>
    </div>
  `;
}

function formatCredits(n) {
  if (n === 0) return '0';
  return n.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 2 });
}

// ─── Team ─────────────────────────────────────────────────────────────────────

function renderTeamSection(db) {
  const members = db.members || [];
  const s = _store.get();

  // Collect all agents across all workgroups for this org
  const orgId = _currentOrgId;
  const wgs = (s.data.workgroups || []).filter(w => w.organization_id === orgId);
  const allAgents = [];
  for (const wg of wgs) {
    const tree = s.data.treeData[wg.id];
    if (tree?.agents) allAgents.push(...tree.agents);
  }

  const memberRows = members.map(m => `
    <div class="org-dash-member-row">
      <span>${escapeHtml(m.name || m.email)}</span>
      <span class="org-dash-role-badge ${m.role === 'owner' ? 'owner' : ''}">${escapeHtml(m.role)}</span>
    </div>
  `).join('') || '<p class="meta">No members.</p>';

  // Agent summary
  const leads = allAgents.filter(a => a.is_lead);
  const modelCounts = {};
  for (const a of allAgents) {
    const model = a.model || 'unknown';
    const short = model.includes('opus') ? 'Opus' :
                  model.includes('sonnet') ? 'Sonnet' :
                  model.includes('haiku') ? 'Haiku' : model;
    modelCounts[short] = (modelCounts[short] || 0) + 1;
  }
  const modelSummary = Object.entries(modelCounts).map(([m, c]) => `${c} ${m}`).join(', ');

  const agentInfo = allAgents.length
    ? `<p><strong>${allAgents.length}</strong> agent${allAgents.length !== 1 ? 's' : ''}${leads.length ? ` (${leads.length} lead${leads.length !== 1 ? 's' : ''})` : ''}</p>
       ${modelSummary ? `<p class="meta">${escapeHtml(modelSummary)}</p>` : ''}`
    : '<p class="meta">No agents.</p>';

  // Pending invites
  let inviteCount = 0;
  for (const wg of wgs) {
    const tree = s.data.treeData[wg.id];
    if (tree?.invites) inviteCount += tree.invites.length;
  }
  const inviteHtml = inviteCount > 0
    ? `<p class="meta">${inviteCount} pending invite${inviteCount !== 1 ? 's' : ''}</p>`
    : '';

  return `
    <div class="org-dash-section">
      <div class="org-dash-section-header"><h4 class="heading-serif">Team</h4></div>
      <div class="org-dash-team-grid">
        <div>
          <h5 class="org-dash-subsection-label">Members</h5>
          ${memberRows}
          ${inviteHtml}
        </div>
        <div>
          <h5 class="org-dash-subsection-label">Agents</h5>
          ${agentInfo}
        </div>
      </div>
    </div>
  `;
}

// ─── Activity Feed ────────────────────────────────────────────────────────────

function renderActivityFeed(db) {
  const items = db.activity || [];

  if (!items.length) {
    return `
      <div class="org-dash-section">
        <div class="org-dash-section-header"><h4 class="heading-serif">Activity</h4></div>
        <p class="meta">No recent activity.</p>
      </div>
    `;
  }

  const rows = items.slice(0, 15).map(item => {
    const time = formatRelativeTime(item.timestamp);
    const typeIcon = item.type === 'message' ? 'msg' :
                     item.type === 'job_completed' ? 'done' :
                     item.type === 'job_cancelled' ? 'cancel' : '';
    return `
      <div class="activity-item ${item.conversation_id ? 'clickable' : ''}" ${item.conversation_id ? `data-conversation="${escapeHtml(item.conversation_id)}" data-workgroup="${escapeHtml(item.workgroup_id || '')}"` : ''}>
        ${typeIcon === 'done' ? '<span class="org-dash-activity-icon done">&#10003;</span>' :
          typeIcon === 'cancel' ? '<span class="org-dash-activity-icon cancel">&#10007;</span>' :
          '<span class="org-dash-activity-icon msg">&#9679;</span>'}
        <span class="activity-summary">${escapeHtml(item.summary || '')}</span>
        <span class="activity-time meta">${escapeHtml(time)}</span>
      </div>
    `;
  }).join('');

  return `
    <div class="org-dash-section">
      <div class="org-dash-section-header"><h4 class="heading-serif">Activity</h4></div>
      ${rows}
    </div>
  `;
}

function formatRelativeTime(iso) {
  const diff = Date.now() - new Date(iso).getTime();
  if (diff < 60000) return 'just now';
  if (diff < 3600000) return Math.floor(diff / 60000) + 'm ago';
  if (diff < 86400000) return Math.floor(diff / 3600000) + 'h ago';
  return Math.floor(diff / 86400000) + 'd ago';
}

// ─── Engagements & Partners ───────────────────────────────────────────────────

function renderEngagementsSection(orgId, db) {
  const s = _store.get();
  const partnerships = s.data.partnerships || [];
  const engagements = db.engagements || [];

  // Pipeline counts
  const pipeline = { proposed: 0, accepted: 0, in_progress: 0, completed: 0 };
  for (const eng of engagements) {
    if (eng.status === 'proposed') pipeline.proposed++;
    else if (eng.status === 'accepted') pipeline.accepted++;
    else if (eng.status === 'in_progress') pipeline.in_progress++;
    else if (eng.status === 'completed' || eng.status === 'reviewed') pipeline.completed++;
  }

  const partnerCount = partnerships.filter(p => p.status === 'accepted').length;

  return `
    <div class="org-dash-section">
      <button class="org-dash-collapse-toggle" aria-expanded="false" data-toggle="engagements-section">
        <svg class="org-dash-collapse-chevron" viewBox="0 0 20 20" fill="none" width="12" height="12">
          <path d="M5 7.5l5 5 5-5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        <h4 class="heading-serif">Engagements &amp; Partners</h4>
        <span class="home-badge">${engagements.length}</span>
      </button>
      <div class="org-dash-collapsible hidden" data-collapsible="engagements-section">
        <div class="org-dash-engagement-stats">
          <span class="meta"><strong>${partnerCount}</strong> partner${partnerCount !== 1 ? 's' : ''}</span>
          <span class="meta"><strong>${pipeline.proposed}</strong> proposed</span>
          <span class="meta"><strong>${pipeline.accepted + pipeline.in_progress}</strong> active</span>
          <span class="meta"><strong>${pipeline.completed}</strong> completed</span>
        </div>
      </div>
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

// ─── Event Wiring ─────────────────────────────────────────────────────────────

function wireEvents(container, orgId) {
  // Workgroup card clicks → drill into workgroup
  container.querySelectorAll('.org-dash-wg-card').forEach(card => {
    card.addEventListener('click', () => {
      const wgId = card.dataset.workgroupId;
      if (wgId) {
        _store.update(s => { s.nav.activeWorkgroupId = wgId; });
        _store.notify('nav.activeWorkgroupId');
        bus.emit('nav:workgroup-selected', { workgroupId: wgId });
      }
    });
  });

  // Activity item clicks → navigate to conversation
  container.querySelectorAll('.activity-item.clickable').forEach(item => {
    item.addEventListener('click', () => {
      const convId = item.dataset.conversation;
      const wgId = item.dataset.workgroup;
      if (convId && wgId) {
        bus.emit('nav:conversation-selected', { workgroupId: wgId, conversationId: convId });
      }
    });
  });

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
